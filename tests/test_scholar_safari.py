"""Offline Safari transport, coverage, capture replay, and cleanup checks."""
import contextlib
import io
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_scholar_captures as captures
from test_scholar_captures import SCHOLAR, URL
import cache_acm_fellow_profiles_safari as ACM
import cache_dblp_profiles_safari as DBLP

REQUEST = URL + '&hl=en&oi=ao&pagesize=100&cstart=0'


def page(count=100, exhausted=False):
    return ('<html><title>Example Person - Google Scholar</title>'
            '<div id="gsc_prf_in">Example Person</div><table>' +
            '<tr class="gsc_a_tr"><td>Paper</td></tr>' * count + '</table>' +
            '<button id="gsc_bpf_more"' + (' disabled=""' if exhausted else '') +
            '>Show more</button></html>')


class SafariTests(unittest.TestCase):
    setUp = captures.ScholarCaptureTests.setUp
    store = captures.ScholarCaptureTests.store

    def run_crawler(self, *extra, expected_exit=0):
        return captures.ScholarCaptureTests.run_crawler(self, '--transport', 'safari', *extra,
                                              expected_exit=expected_exit)

    def test_coverage_and_redirect_validation(self):
        for count, exhausted, expected in ((100, False, 'ok'), (79, True, 'ok'),
                                           (0, True, 'ok'), (20, False, 'validation_error'),
                                           (101, True, 'validation_error')):
            with self.subTest(count=count):
                result = SCHOLAR.classify_safari(REQUEST, REQUEST, page(count, exhausted))
                self.assertEqual(result['status'], expected)
                self.assertEqual(result['publication_count'], count)
        self.assertEqual(SCHOLAR.classify_safari(REQUEST, URL + 'other', page())['status'], 'redirect_review')
        self.assertEqual(SCHOLAR.classify_safari(REQUEST, 'https://accounts.google.com/', page())['status'], 'redirect_review')
        self.assertEqual(SCHOLAR.classify_safari(REQUEST, REQUEST, page()[:-7])['status'], 'validation_error')
        self.assertEqual(SCHOLAR.classify_safari(REQUEST, REQUEST, page().replace('gsc_prf_in', 'other'))['status'], 'no_title')
        self.assertEqual(SCHOLAR.classify_safari(REQUEST.replace('100', '20'), REQUEST, page(20))['status'], 'ok')

    def test_publication_block_phrases_do_not_stop_crawl(self):
        self.source.write_text('name,google_scholar_profile\nExample Person,' + URL +
                               '\nSecond Person,' + URL + '2\n')
        body = page().replace('Paper', 'Not a robot: unusual traffic, captcha and /sorry/')
        outputs = [REQUEST + '\n' + body,
                   REQUEST.replace('user=example', 'user=example2') + '\n' + body]
        with patch.object(sys, 'platform', 'darwin'), patch.object(DBLP, 'open_window', return_value=42), \
             patch.object(ACM, 'close_window'), patch.object(ACM, 'run_applescript', side_effect=outputs) as fetch:
            entry = self.run_crawler()
        self.assertEqual(entry['status'], 'ok')
        self.assertEqual(fetch.call_count, 2)
        with patch.object(DBLP, 'open_window', side_effect=AssertionError('Safari')):
            self.assertEqual(self.run_crawler('--rebuild-cache')['status'], 'ok')

    def test_retry_status_selects_retained_failure(self):
        for failure in (captures.BLOCK_HTML, page(20)):
            with self.subTest(failure=failure), patch.object(sys, 'platform', 'darwin'), \
                 patch.object(DBLP, 'open_window', return_value=42), patch.object(ACM, 'close_window'):
                with patch.object(ACM, 'run_applescript', return_value=REQUEST + '\n' + page()):
                    good = self.run_crawler('--refresh')
                with patch.object(ACM, 'run_applescript', return_value=REQUEST + '\n' + failure):
                    failed = self.run_crawler('--refresh', expected_exit=1)
                self.assertEqual(failed['status'], 'ok')
                self.assertEqual(failed['capture_id'], good['capture_id'])
                status = failed['last_fetch_error']['status']
                with patch.object(ACM, 'run_applescript', side_effect=AssertionError('unselected retry')):
                    skipped = self.run_crawler('--retry-status', 'browser_error')
                self.assertEqual(skipped['last_fetch_error']['status'], status)
                with patch.object(ACM, 'run_applescript', return_value=REQUEST + '\n' + page()) as fetch:
                    recovered = self.run_crawler('--retry-status', status)
                fetch.assert_called_once()
                self.assertEqual(recovered['status'], 'ok')
                self.assertNotIn('last_fetch_error', recovered)
                self.assertNotEqual(recovered['capture_id'], good['capture_id'])

    def test_default_transport(self):
        with patch.object(sys, 'argv', ['crawler', '--data', str(self.source)]):
            args = SCHOLAR.parse_args()
        self.assertEqual(args.transport, 'safari')
        self.assertEqual(args.page_size, 100)
        self.assertEqual(args.delay, 15)
        self.assertEqual(args.delay_jitter, 5)
        self.assertEqual(args.batch_size, 25)
        self.assertEqual(args.batch_pause, 75)
        self.assertEqual(args.batch_pause_jitter, 15)

    def test_capture_and_offline_rebuild(self):
        with patch.object(sys, 'platform', 'darwin'), patch.object(DBLP, 'open_window', return_value=42) as opened, \
             patch.object(ACM, 'close_window') as closed, \
             patch.object(ACM, 'run_applescript', return_value=REQUEST + '\n' + page()) as fetch, \
             patch.object(SCHOLAR.urllib.request, 'urlopen', side_effect=AssertionError('HTTP')):
            entry = self.run_crawler()
        opened.assert_called_once()
        closed.assert_called_once_with(42)
        self.assertEqual(fetch.call_args.args[2], REQUEST)
        self.assertEqual(entry['publication_count'], 100)
        self.assertIsNone(entry['status_code'])
        self.assertEqual(entry['body_source'], 'safari-page-source')
        self.assertEqual((self.work / entry['html_path']).read_text(), page())
        capture = self.store().manifest['captures'][0]
        self.assertEqual(capture['fetch_method'], 'safari-applescript')
        self.assertEqual(capture['body_source'], 'safari-page-source')
        with patch.object(DBLP, 'open_window', side_effect=AssertionError('Safari')):
            rebuilt = self.run_crawler('--rebuild-cache')
            resumed = self.run_crawler()
        self.assertEqual(rebuilt['publication_count'], 100)
        self.assertEqual(resumed['capture_id'], entry['capture_id'])
        self.assertEqual(json.loads(self.report.read_text())['entries'][0]['publication_count'], 100)

    def test_failures_stop_without_retry_and_survive_replay(self):
        self.source.write_text('name,google_scholar_profile\nExample Person,' + URL +
                               '\nSecond Person,' + URL + '2\n')
        for final_url, body, expected in ((REQUEST, captures.BLOCK_HTML, 'blocked'),
                                           ('https://www.google.com/sorry/index', '<html>Sorry</html>', 'blocked'),
                                           (REQUEST, page(20), 'validation_error'),
                                           (URL + 'other', page(), 'redirect_review')):
            with self.subTest(expected=expected), patch.object(sys, 'platform', 'darwin'), \
                 patch.object(DBLP, 'open_window', return_value=42), patch.object(ACM, 'close_window') as closed, \
                 patch.object(ACM, 'run_applescript', return_value=final_url + '\n' + body) as fetch:
                entry = self.run_crawler('--refresh', '--max-retries', '3', expected_exit=1)
            self.assertEqual(entry['status'], expected)
            self.assertEqual(fetch.call_count, 1)
            closed.assert_called_once_with(42)
            with patch.object(DBLP, 'open_window', side_effect=AssertionError('Safari')):
                rebuilt = self.run_crawler('--rebuild-cache')
            self.assertEqual(rebuilt['status'], expected)

    def test_cleanup_on_interrupt_and_browser_error(self):
        for error in (KeyboardInterrupt(), subprocess.TimeoutExpired('osascript', 60)):
            with patch.object(sys, 'platform', 'darwin'), patch.object(DBLP, 'open_window', return_value=42), \
                 patch.object(ACM, 'close_window') as closed, patch.object(ACM, 'run_applescript', side_effect=error) as fetch:
                if isinstance(error, KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt):
                        self.run_crawler()
                else:
                    entry = self.run_crawler(expected_exit=1)
                    self.assertEqual(entry['status'], 'browser_error')
                closed.assert_called_once_with(42)
                self.assertEqual(fetch.call_count, 1)

    def test_no_requests_does_not_open_browser(self):
        with patch.object(DBLP, 'open_window', side_effect=AssertionError('Safari')):
            with patch.object(sys, 'argv', ['crawler', '--data', str(self.source), '--cache', str(self.cache),
                                         '--report', str(self.report), '--limit-new', '0']), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(SCHOLAR.main(), 0)


if __name__ == '__main__':
    unittest.main()
