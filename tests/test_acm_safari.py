"""Offline checks for Safari transport, resumability, and bounded retries."""
import contextlib
import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import cache_acm_fellow_profiles_safari as safari

HTML = '''<html><head><title>Dr. Example Person</title></head><body>
<h1>Dr. Example Person</h1><section class="awards-winners__citation">
<h2>ACM Fellows</h2><h3 class="awards-winners__location">USA - 2025</h3>
<p class="awards-winners__citation-short">For useful contributions.</p>
</section></body></html>'''
URL = 'https://awards.acm.org/award-recipients/example'


class SafariTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'tmp').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp')
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.source = self.work / 'input.csv'
        self.cache = self.work / 'cache.json'
        self.report = self.work / 'report.json'
        self.state = self.work / 'cache.status.json'
        self.write_input([URL])

    def write_input(self, urls):
        with self.source.open('w', newline='') as stream:
            writer = csv.writer(stream, lineterminator='\n')
            writer.writerow(['name', 'year', 'acm_fellow_profile'])
            writer.writerows(['Example Person', '2025', url] for url in urls)

    def run_crawler(self, *extra):
        args = [safari.__file__, '--data', str(self.source), '--cache', str(self.cache),
                '--report', str(self.report), '--delay', '0', '--backoff', '0',
                '--backoff-jitter', '0', *extra]
        with patch.object(sys, 'argv', args), contextlib.redirect_stdout(io.StringIO()):
            return safari.main()

    def test_cache_only_never_opens_safari_and_preserves_input(self):
        before = self.source.read_bytes()
        with patch.object(safari, 'open_window', side_effect=AssertionError('Opened Safari')):
            self.assertEqual(self.run_crawler('--limit-new', '0'), 0)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(json.loads(self.report.read_text())['status_counts'], {'missing': 1})

    def test_native_html_parsing_does_not_invent_http_status(self):
        with patch.object(safari, 'run_applescript', return_value=URL + '\n' + HTML):
            entry = safari.fetch_profile(123, URL, 30)
        self.assertEqual(entry['status'], 'ok')
        self.assertEqual(entry['page_name'], 'Example Person')
        self.assertEqual(entry['year'], '2025')
        self.assertEqual(entry['html'], HTML)
        self.assertIsNone(entry['status_code'])
        self.assertEqual(safari.entry_from_html(URL, '<html>404 - Your Page Could Not Be Found</html>')['status'], 'http_error')
        self.assertEqual(safari.entry_from_html(URL, '<html>Sorry, you have been blocked</html>')['status'], 'blocked')

    def test_rejects_wrong_url_incomplete_html_and_non_http_input(self):
        for output in ('https://example.org\n' + HTML, URL + '\n<html>unfinished'):
            with patch.object(safari, 'run_applescript', return_value=output):
                self.assertEqual(safari.fetch_profile(123, URL, 30)['status'], 'url_error')
        with patch.object(safari, 'run_applescript', side_effect=AssertionError('Unexpected browser call')):
            self.assertEqual(safari.fetch_profile(123, 'file:///tmp/input', 30)['status'], 'invalid_url')

    def test_resume_retries_failure_preserves_other_apps_and_does_not_edit_csv(self):
        self.write_input([URL, URL, '', URL + '2'])
        first = safari.entry_from_html(URL, HTML)
        self.cache.write_text(json.dumps({URL: first, URL + '2': {'status': 'blocked'}, 'other-app': first}))
        before = self.source.read_bytes()
        with patch.object(safari, 'open_window', return_value=123), patch.object(safari, 'close_window') as close, patch.object(safari, 'fetch_profile', return_value=safari.entry_from_html(URL + '2', HTML)) as fetch:
            self.assertEqual(self.run_crawler(), 0)
            fetch.assert_called_once_with(123, URL + '2', 30)
            close.assert_called_once_with(123)
        self.assertEqual(self.source.read_bytes(), before)
        result = json.loads(self.cache.read_text())
        self.assertEqual(result[URL], first)
        self.assertEqual(set(result), {URL, URL + '2', 'other-app'})
        with patch.object(safari, 'open_window', side_effect=AssertionError('Opened Safari')):
            self.assertEqual(self.run_crawler(), 0)

    def test_persistent_block_stops_before_next_profile_and_saves_failure(self):
        self.write_input([URL, URL + '2'])
        entry = safari.entry_from_html(URL, '<html>Sorry, you have been blocked</html>')
        with patch.object(safari, 'open_window', return_value=123), patch.object(safari, 'close_window'), patch.object(safari, 'fetch_profile', return_value=entry) as fetch, patch.object(safari.time, 'sleep'):
            self.assertEqual(self.run_crawler('--max-retries', '2'), 1)
        self.assertEqual(fetch.call_count, 3)
        self.assertTrue(all(c.args[1] == URL for c in fetch.call_args_list))
        self.assertEqual(json.loads(self.state.read_text())['state'], 'paused')
        self.assertEqual(json.loads(self.cache.read_text())[URL]['status'], 'blocked')

    def test_pilot_mismatch_stops_and_retains_html_for_review(self):
        self.write_input([URL, URL + '2'])
        entry = safari.entry_from_html(URL, HTML.replace('Example Person', 'Different Researcher'))
        with patch.object(safari, 'open_window', return_value=123), patch.object(safari, 'close_window'), patch.object(safari, 'fetch_profile', return_value=entry) as fetch:
            self.assertEqual(self.run_crawler(), 1)
        self.assertEqual(fetch.call_count, 1)
        self.assertIn('Different Researcher', json.loads(self.cache.read_text())[URL]['html'])

    def test_retries_count_toward_batch_cooldown(self):
        self.write_input([URL, URL + '2'])
        good = safari.entry_from_html(URL, HTML)
        blocked = safari.entry_from_html(URL, '<html>Sorry, you have been blocked</html>')
        with patch.object(safari, 'open_window', return_value=123), patch.object(safari, 'close_window'), patch.object(safari, 'fetch_profile', side_effect=[blocked, good, good]), patch.object(safari.time, 'sleep') as sleep:
            self.assertEqual(self.run_crawler('--batch-size', '2', '--batch-pause', '75', '--batch-pause-jitter', '0'), 0)
        self.assertEqual([c.args[0] for c in sleep.call_args_list if c.args[0] > 0], [75])

    def test_refresh_and_limit_only_replace_selected_entries(self):
        self.write_input([URL, URL + '2'])
        old = safari.entry_from_html(URL, HTML)
        self.cache.write_text(json.dumps({URL: old, URL + '2': old}))
        updated = {**old, 'fetched_at': 'new'}
        with patch.object(safari, 'open_window', return_value=123), patch.object(safari, 'close_window'), patch.object(safari, 'fetch_profile', return_value=updated) as fetch:
            self.assertEqual(self.run_crawler('--refresh', '--limit-new', '1'), 0)
        self.assertEqual(fetch.call_count, 1)
        result = json.loads(self.cache.read_text())
        self.assertEqual(result[URL], updated)
        self.assertEqual(result[URL + '2'], old)

    def test_permission_denial_stops_without_retries(self):
        failure = subprocess.CalledProcessError(1, ['osascript'], stderr='Not authorized to send Apple events to Safari. (-1743)')
        with patch.object(safari, 'open_window', return_value=123), patch.object(safari, 'close_window'), patch.object(safari, 'run_applescript', side_effect=failure) as apple:
            self.assertEqual(self.run_crawler(), 1)
        self.assertEqual(apple.call_count, 1)


if __name__ == '__main__':
    unittest.main()
