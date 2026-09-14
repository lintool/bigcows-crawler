"""Regressions for profile validation, historical evidence, and offline audits."""
import contextlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'tests')]
import cache_acm_fellow_profiles as acm
import compare_acm_fellow_profiles as compare
import test_acm_safari as fixtures
import cache_acm_fellow_profiles_safari as safari
from test_acm_turing import LEGACY

HTML, URL = fixtures.HTML, fixtures.URL


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SafariTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.work = self.fixture.work

    def test_absent_optional_columns_are_not_mismatches_but_blanks_are(self):
        cache = {URL: safari.entry_from_html(URL, HTML)}
        minimal = {'name': 'Example Person', 'acm_fellow_profile': URL}
        report = acm.build_report(acm.unique_profiles([minimal]), cache)
        self.assertEqual(report['review_candidate_count'], 0)
        for field in ('year', 'location', 'citation'):
            self.assertIsNone(report['entries'][0][field + '_match'])
        self.assertEqual(compare.compare_rows([minimal], cache)['difference_counts'], {})
        blank = {**minimal, 'year': '', 'location': '', 'citation': ''}
        report = acm.build_report(acm.unique_profiles([blank]), cache)
        self.assertEqual(report['review_candidate_count'], 1)
        for field in ('year', 'location', 'citation'):
            self.assertFalse(report['entries'][0][field + '_match'])
        self.assertEqual(compare.compare_rows([blank], cache)['difference_counts'],
                         {'year': 1, 'location': 1, 'citation': 1})

    def test_fetch_and_audit_share_error_and_legacy_classification(self):
        row = {'name': 'Example Person', 'acm_fellow_profile': URL}
        cases = [('', 'missing_html'), ('<html>404 - your page could not be found</html>', 'http_error'),
                 ('<html>Too Many Requests</html>', 'blocked'),
                 (HTML, 'no_turing_award'), (LEGACY, 'ok'),
                 (LEGACY.replace('</html>', '<script src="cloudflareapps.js"></script></html>'), 'ok'),
                 (LEGACY.replace('</html>', 'cf-chl-test</html>'), 'blocked')]
        for body, expected in cases:
            with self.subTest(expected=expected, body=body[:30]):
                fetched = safari.entry_from_html(URL, body, 'turing')
                # Ignore stale parsed fields/status when re-auditing raw HTML.
                audited = compare.compare_rows([row], {URL: {'html': body, 'status': 'ok'}}, 'turing')['entries'][0]
                self.assertEqual(fetched['status'], expected)
                self.assertEqual(audited['status'], expected)

    def test_http_success_response_with_acm_error_html_is_not_a_profile(self):
        class Response:
            status = 200
            headers = None
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'<html>404 - your page could not be found</html>'
        with patch.object(acm.urllib.request, 'urlopen', return_value=Response()):
            result = acm.fetch_profile(URL)
        self.assertEqual((result['status'], result['status_code']), ('http_error', 200))

    def test_progress_counts_distinct_attempted_profiles_without_lag(self):
        f = self.fixture
        f.write_input([URL, URL + '2'])
        seen = []
        def fetch(*args):
            state = json.loads(f.state.read_text())
            seen.append((state['fetched_this_run'], state['attempts_this_run']))
            return {'status': 'blocked', 'html': ''} if len(seen) == 1 else safari.entry_from_html(URL, HTML)
        with patch.object(safari, 'open_window', return_value=123), patch.object(safari, 'close_window'), patch.object(safari, 'fetch_profile', side_effect=fetch), patch.object(safari.time, 'sleep'):
            self.assertEqual(f.run_crawler(), 0)
        self.assertEqual(seen, [(0, 0), (1, 1), (1, 2)])
        state = json.loads(f.state.read_text())
        self.assertEqual((state['selected_profiles'], state['fetched_this_run'], state['attempts_this_run']), (2, 2, 3))

    def test_paused_first_profile_still_counts_as_attempted(self):
        f = self.fixture
        with patch.object(safari, 'open_window', return_value=123), patch.object(safari, 'close_window'), patch.object(safari, 'fetch_profile', return_value={'status': 'timeout', 'html': ''}):
            self.assertEqual(f.run_crawler('--max-retries', '0'), 1)
        state = json.loads(f.state.read_text())
        self.assertEqual((state['state'], state['fetched_this_run'], state['attempts_this_run']), ('paused', 1, 1))

    def test_void_elements_and_multiple_awards(self):
        other = '<section class="awards-winners__citation"><h2>Another Award</h2><h3 class="awards-winners__location">France - 2024</h3><p class="awards-winners__citation-short">Wrong citation.</p></section>'
        for tag in ('<br>', '<br/>', '<img src="x">', '<input>', '<hr>'):
            body = HTML.replace('useful contributions', 'useful ' + tag + ' contributions')
            body = body.replace('</body>', other + '</body>')
            fields = acm.parse_profile_html(body)
            self.assertEqual(fields['citation'], 'For useful contributions.')
            self.assertEqual(fields['year'], '2025')
            self.assertEqual(fields['location'], 'USA')
            self.assertEqual(fields['award_heading'], 'ACM Fellows')

    def test_name_compatibility_does_not_conflate_full_first_names(self):
        for left, right in [('John Smith', 'Jane Smith'), ('John A Smith', 'James A Smith'), ('John Smith', 'John Jones')]:
            self.assertFalse(acm.compatible_name(left, right))
        for left, right in [('J. Smith', 'John Smith'), ('John Smith', 'John A. Smith'), ('Nikolaj Bjørner', 'Bjorner Nikolaj'), ('Giovanni De Micheli', 'Giovanni Demicheli'), ('Urs Hölzle', 'Urs Holzle')]:
            self.assertTrue(acm.compatible_name(left, right), (left, right))

    def test_failed_pilot_stays_blocked_until_explicit_retry_or_acceptance(self):
        f = self.fixture
        bad = safari.entry_from_html(URL, HTML.replace('Example Person', 'Different Researcher'))
        good = safari.entry_from_html(URL, HTML)
        with patch.object(safari, 'open_window', return_value=123), patch.object(safari, 'close_window'), patch.object(safari, 'fetch_profile', return_value=bad) as fetch:
            self.assertEqual(f.run_crawler(), 1)
            with patch.object(safari, 'open_window', side_effect=AssertionError('Reopened browser')):
                self.assertEqual(f.run_crawler('--pilot-size', '0'), 1)
                self.assertEqual(f.run_crawler('--limit-new', '0'), 1)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(f.run_crawler('--retry-status', 'validation_error', '--pilot-size', '0'), 1)
        with patch.object(safari, 'open_window', return_value=123), patch.object(safari, 'close_window'), patch.object(safari, 'fetch_profile', return_value=good):
            self.assertEqual(f.run_crawler('--retry-status', 'validation_error'), 0)
        f.cache.write_text(json.dumps({URL: {**bad, 'status': 'validation_error', 'validation_error': 'Reviewed variant'}}))
        with patch.object(safari, 'open_window', side_effect=AssertionError('Opened browser')):
            self.assertEqual(f.run_crawler('--accept-profile', URL), 0)
        self.assertEqual(json.loads(f.cache.read_text())[URL]['accepted_validation_error'], 'Reviewed variant')

    def test_failed_refresh_retains_good_html_and_retries_last_attempt(self):
        f = self.fixture
        original = safari.entry_from_html(URL, HTML)
        f.cache.write_text(json.dumps({URL: original}))
        failure = {'status': 'timeout', 'html': '', 'error': 'Test timeout'}
        with patch.object(safari, 'open_window', return_value=123), patch.object(safari, 'close_window'), patch.object(safari, 'fetch_profile', return_value=failure):
            self.assertEqual(f.run_crawler('--refresh', '--max-retries', '0'), 1)
        saved = json.loads(f.cache.read_text())[URL]
        self.assertEqual(saved['html'], HTML)
        self.assertEqual(saved['fetched_at'], original['fetched_at'])
        self.assertEqual(saved['last_attempt']['status'], 'timeout')
        report = json.loads(f.report.read_text())
        self.assertEqual(report['review_candidate_count'], 1)
        with patch.object(safari, 'open_window', return_value=123), patch.object(safari, 'close_window'), patch.object(safari, 'fetch_profile', return_value=original) as fetch:
            self.assertEqual(f.run_crawler(), 0)
            fetch.assert_called_once()
        self.assertNotIn('last_attempt', json.loads(f.cache.read_text())[URL])

    def test_manifest_rejects_changed_input_and_dates_before_writing(self):
        f = self.fixture
        self.assertEqual(f.run_crawler('--limit-new', '0'), 0)
        before = {p: p.read_bytes() for p in self.work.iterdir() if p != f.source}
        f.write_input([URL, URL + '2'])
        with patch.object(safari, 'open_window', side_effect=AssertionError('Opened browser')), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(f.run_crawler('--limit-new', '0'), 1)
        self.assertTrue(all(p.read_bytes() == content for p, content in before.items()))
        f.write_input([URL])
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(f.run_crawler('--crawl-date', '2026-09-14', '--limit-new', '0'), 1)
        copied = self.work / 'copy.csv'
        copied.write_bytes(f.source.read_bytes())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(f.run_crawler('--data', str(copied), '--report', str(f.source), '--limit-new', '0'), 1)
        self.assertEqual(f.source.read_bytes(), copied.read_bytes())

    def test_http_entry_point_honors_manifest_and_preserves_failed_refresh(self):
        f = self.fixture
        good = safari.entry_from_html(URL, HTML)
        f.cache.write_text(json.dumps({URL: good}))
        argv = [acm.__file__, '--data', str(f.source), '--crawl-date', '2026-09-13', '--cache', str(f.cache), '--report', str(f.report), '--refresh', '--delay', '0']
        with patch.object(sys, 'argv', argv), patch.object(acm, 'fetch_profile', return_value={'status': 'blocked', 'html': 'blocked'}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(acm.main(), 0)
        self.assertEqual(json.loads(f.cache.read_text())[URL]['html'], HTML)
        f.write_input([URL + '2'])
        with patch.object(sys, 'argv', argv), patch.object(acm, 'fetch_profile', side_effect=AssertionError('Network')), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(acm.main(), 1)

    def test_comparison_reparses_and_keeps_all_artifacts_unchanged(self):
        f = self.fixture
        f.write_input([URL, '', URL + 'missing', URL])
        entry = safari.entry_from_html(URL, HTML)
        f.cache.write_text(json.dumps({URL: {**entry, 'year': '1900'}}))
        f.report.write_text('original report')
        f.state.write_text('original state')
        args = SimpleNamespace(cache=f.cache, data=f.source, report=f.report, state=f.state, crawl_date='2026-09-13')
        acm.ensure_manifest(args)
        before = {p: p.read_bytes() for p in self.work.iterdir()}
        output = io.StringIO()
        argv = [compare.__file__, '--data', str(f.source), '--crawl-date', '2026-09-13', '--cache', str(f.cache)]
        with patch.object(sys, 'argv', argv), contextlib.redirect_stdout(output):
            self.assertEqual(compare.main(), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report['status_counts'], {'ok': 2, 'blank_url': 1, 'missing': 1})
        self.assertEqual(report['entries'][0]['parsed']['year'], '2025')
        self.assertEqual(report['duplicate_urls'], {URL: [1, 4]})
        self.assertTrue(all(p.read_bytes() == content for p, content in before.items()))
        self.assertEqual(set(self.work.iterdir()), set(before))
        for path in (f.cache, f.report, f.state, f.source):
            with patch.object(sys, 'argv', argv + ['--output', str(path)]), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(compare.main(), 1)
        self.assertTrue(all(p.read_bytes() == content for p, content in before.items()))


if __name__ == '__main__':
    unittest.main()
