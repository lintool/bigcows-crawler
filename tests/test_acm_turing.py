"""Offline coverage of shared ACM award selection and crawl preparation."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'tests')]
import cache_acm_fellow_profiles as acm
import cache_acm_fellow_profiles_safari as safari
import compare_acm_fellow_profiles as compare
import test_acm_safari as fixtures

TURING = fixtures.HTML.replace('ACM Fellows', 'ACM A. M. Turing Award')
LEGACY = '''<html><title>Example Person - A.M. Turing Award Laureate</title>
<p>Biography: 1966, 1994, and 2020.</p>
<h1 class="country"><a>Example Person</a><img alt="Profile link"></h1>
<div class="description"><span>United States – 2025</span></div>
<div class="citation"><span class="label">CITATION</span>
<p>For useful<br>contributions.</p></div></html>'''


class TuringTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SafariTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_selects_award_not_first_year_or_first_section(self):
        both = TURING.replace('</body>', fixtures.HTML.replace('2025', '1994') + '</body>')
        self.assertEqual(acm.parse_profile_html(both)['year'], '1994')
        parsed = acm.parse_profile_html(both, 'turing')
        self.assertEqual(parsed['year'], '2025')
        self.assertEqual(parsed['award_heading'], 'ACM A. M. Turing Award')
        self.assertEqual(safari.entry_from_html(fixtures.URL, fixtures.HTML, 'turing')['status'], 'no_turing_award')

    def test_legacy_layout_and_keywords_page(self):
        parsed = acm.parse_profile_html(LEGACY, 'turing')
        self.assertEqual((parsed['page_name'], parsed['year'], parsed['location'], parsed['citation']),
                         ('Example Person', '2025', 'United States', 'For useful contributions.'))
        self.assertEqual(acm.parse_profile_html(LEGACY)['award_heading'], '')
        keywords = LEGACY.replace('class="citation"', 'class="keywords"')
        self.assertEqual(safari.entry_from_html(fixtures.URL, keywords, 'turing')['status'], 'no_turing_award')

    def test_prepare_is_browser_free_and_separates_same_date_awards(self):
        f = self.fixture
        with patch.object(acm, 'CRAWLER_ROOT', f.work), patch.object(safari, 'open_window', side_effect=AssertionError('Opened Safari')):
            def prepare(award):
                argv = [safari.__file__, '--data', str(f.source), '--crawl-date', '2026-09-13', '--award', award, '--prepare-only']
                with patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(safari.main(), 0)
            prepare('fellows')
            originals = {p: p.read_bytes() for p in (f.work / '.cache').iterdir()}
            prepare('turing')
            state = json.loads(acm.crawl_path('state', '2026-09-13', 'turing').read_text())
            self.assertEqual(state['state'], 'prepared')
            self.assertEqual(state['attempts_this_run'], 0)
            self.assertIsNone(state['safari_window_id'])
            self.assertEqual(json.loads(acm.crawl_path('cache', '2026-09-13', 'turing').read_text()), {})
            self.assertTrue(all(p.read_bytes() == old for p, old in originals.items()))

    def test_custom_cache_cannot_resume_with_different_award(self):
        f = self.fixture
        with patch.object(safari, 'open_window', side_effect=AssertionError('Opened Safari')):
            self.assertEqual(f.run_crawler('--prepare-only'), 0)
            before = {p: p.read_bytes() for p in f.work.iterdir()}
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(f.run_crawler('--award', 'turing', '--prepare-only'), 1)
            self.assertTrue(all(p.read_bytes() == old for p, old in before.items()))

    def test_turing_fetch_selection_resume_and_read_only_comparison(self):
        f = self.fixture
        with patch.object(safari, 'open_window', return_value=123), patch.object(safari, 'close_window'), patch.object(safari, 'run_applescript', return_value=fixtures.URL + '\n' + TURING) as apple:
            self.assertEqual(f.run_crawler('--award', 'turing'), 0)
            self.assertEqual(f.run_crawler('--award', 'turing'), 0)
            self.assertEqual(apple.call_count, 1)
        before = {p: p.read_bytes() for p in f.work.iterdir()}
        argv = [compare.__file__, '--award', 'turing', '--data', str(f.source), '--crawl-date', '2026-09-13', '--cache', str(f.cache)]
        stdout = io.StringIO()
        with patch.object(sys, 'argv', argv), contextlib.redirect_stdout(stdout):
            self.assertEqual(compare.main(), 0)
        self.assertEqual(json.loads(stdout.getvalue())['status_counts'], {'ok': 1})
        self.assertTrue(all(p.read_bytes() == old for p, old in before.items()))

    def test_comparison_can_reuse_raw_html_from_fellows_crawl(self):
        f = self.fixture
        both = TURING.replace('</body>', fixtures.HTML + '</body>')
        f.cache.write_text(json.dumps({fixtures.URL: safari.entry_from_html(fixtures.URL, both)}))
        self.assertEqual(f.run_crawler('--prepare-only'), 0)
        before = {p: p.read_bytes() for p in f.work.iterdir()}
        argv = [compare.__file__, '--award', 'turing', '--data', str(f.source), '--crawl-date', '2026-09-13', '--cache', str(f.cache)]
        stdout = io.StringIO()
        with patch.object(sys, 'argv', argv), contextlib.redirect_stdout(stdout):
            self.assertEqual(compare.main(), 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report['award'], 'turing')
        self.assertEqual(report['crawl_award'], 'fellows')
        self.assertEqual(report['status_counts'], {'ok': 1})
        self.assertTrue(all(p.read_bytes() == old for p, old in before.items()))


if __name__ == '__main__':
    unittest.main()
