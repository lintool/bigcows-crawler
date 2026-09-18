"""Offline checks for DBLP Safari capture, isolation, and resume pacing."""

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import cache_dblp_profiles_safari as safari

URL = 'https://dblp.org/pid/56/4447'
HTML = '<html><head><title>dblp: Adam Wierman</title></head><body><h1><span itemprop="name">Adam Wierman</span></h1></body></html>'
BLOCK = '<html><title>Making sure you are not a bot!</title><script id="anubis_challenge">{}</script></html>'


class DblpSafariTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'tmp').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp')
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.source = self.work / 'source.csv'
        self.source.write_text(f'name,dblp_profile\nAdam Wierman,{URL}\nAdam Wierman,{URL}2\n')
        self.run = self.work / 'run'

    def run_crawler(self, *args):
        argv = ['crawler', '--data', str(self.source), '--run-dir', str(self.run),
                '--delay', '0', '--batch-pause', '0', *args]
        with patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
            return safari.main()

    def test_profile_redirect_and_browser_status(self):
        with patch.object(safari, 'run_applescript', return_value=URL + '.html\n' + HTML):
            result = safari.fetch_profile(123, URL, 60)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['title'], 'Adam Wierman')
        self.assertIsNone(result['status_code'])
        self.assertEqual(result['final_url'], URL + '.html')

    def test_blocks_and_incomplete_documents_stop_but_redirects_need_review(self):
        self.assertEqual(safari.classify(URL, URL, BLOCK)['status'], 'blocked')
        for final in (URL + '2', 'https://example.org/pid/56/4447'):
            self.assertEqual(safari.classify(URL, final, HTML)['status'], 'redirect_review')
        self.assertEqual(safari.classify(URL, URL + '2', BLOCK)['status'], 'blocked')
        self.assertEqual(safari.classify(URL, URL, HTML.replace('</html>', ''))['status'], 'url_error')
        self.assertEqual(safari.classify(URL, URL, '<html><title>404</title></html>')['status'], 'no_profile')
        with patch.object(safari, 'run_applescript', side_effect=AssertionError('Browser opened')):
            self.assertEqual(safari.fetch_profile(123, 'file:///tmp/a', 60)['status'], 'invalid_url')

    def test_redirect_in_pilot_continues_and_resume_does_not_refetch(self):
        redirected = safari.classify(URL, URL + '3.html', HTML)
        good = safari.classify(URL + '2', URL + '2.html', HTML)
        with patch.object(safari, 'open_window', return_value=123), patch.object(safari, 'close_window'), patch.object(safari, 'fetch_profile', side_effect=[redirected, good]) as fetch:
            self.assertEqual(self.run_crawler(), 0)
            self.assertEqual(fetch.call_count, 2)
        cache = json.loads((self.run / 'cache.json').read_text())
        self.assertEqual(cache[URL]['status'], 'redirect_review')
        self.assertEqual(cache[URL]['requested_url'], URL)
        self.assertEqual(cache[URL]['final_url'], URL + '3.html')
        self.assertEqual((self.run / cache[URL]['html_path']).read_text(), HTML)
        report = json.loads((self.run / 'report.json').read_text())
        self.assertEqual(report['review_candidate_count'], 1)
        self.assertEqual(report['review_candidates'][0]['status'], 'redirect_review')
        with patch.object(safari, 'open_window', side_effect=AssertionError('Browser opened')):
            self.assertEqual(self.run_crawler(), 0)

    def test_resume_skips_success_and_retains_capture_and_input(self):
        before = self.source.read_bytes()
        def capture(window, url, timeout):
            return safari.classify(url, url + '.html', HTML)
        with patch.object(safari, 'open_window', return_value=123), patch.object(safari, 'close_window') as close, patch.object(safari, 'fetch_profile', side_effect=capture) as fetch:
            self.assertEqual(self.run_crawler('--limit-new', '1'), 0)
            self.assertEqual(self.run_crawler(), 0)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(close.call_count, 2)
        with patch.object(safari, 'open_window', side_effect=AssertionError('Browser opened')):
            self.assertEqual(self.run_crawler(), 0)
        cache = json.loads((self.run / 'cache.json').read_text())
        self.assertEqual((self.run / cache[URL]['html_path']).read_text(), HTML)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual((self.run / 'input.csv').read_bytes(), before)
        self.assertIsNone(json.loads((self.run / 'state.json').read_text())['safari_window_id'])

    def test_block_pauses_before_next_profile_and_requires_explicit_retry(self):
        with patch.object(safari, 'open_window', return_value=123), patch.object(safari, 'close_window'), patch.object(safari, 'fetch_profile', return_value=safari.classify(URL, URL, BLOCK)) as fetch:
            self.assertEqual(self.run_crawler(), 1)
            self.assertEqual(fetch.call_count, 1)
        with patch.object(safari, 'open_window', side_effect=AssertionError('Browser opened')):
            self.assertEqual(self.run_crawler(), 1)
        self.assertEqual(json.loads((self.run / 'cache.json').read_text())[URL]['status'], 'blocked')

    def test_cooldown_persists_across_pilot_and_resume(self):
        with patch.object(safari, 'open_window', return_value=123), patch.object(safari, 'close_window'), patch.object(safari, 'fetch_profile', return_value=safari.classify(URL, URL, HTML)), patch.object(safari.time, 'time', return_value=1000), patch.object(safari.time, 'sleep') as sleep:
            args = ('--batch-size', '1', '--batch-pause', '75', '--batch-pause-jitter', '0')
            self.assertEqual(self.run_crawler(*args, '--limit-new', '1'), 0)
            self.assertEqual(self.run_crawler(*args), 0)
            self.assertEqual([c.args[0] for c in sleep.call_args_list if c.args[0] > 0], [75])

    def test_changed_input_rejected_before_browser_or_cache_write(self):
        self.assertEqual(self.run_crawler('--limit-new', '0'), 0)
        before = (self.run / 'cache.json').read_bytes()
        self.source.write_text(self.source.read_text() + '\n')
        with patch.object(safari, 'open_window', side_effect=AssertionError('Browser opened')):
            with self.assertRaisesRegex(ValueError, 'Input changed'):
                self.run_crawler()
        self.assertEqual((self.run / 'cache.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
