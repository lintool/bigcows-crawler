"""Offline regressions for crawl ownership, citation links, and resume pacing."""
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


class SafeguardTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.SafariTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.root_patch = patch.object(acm, 'CRAWLER_ROOT', self.f.work)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def prepare(self, day='2026-09-13', *extra):
        argv = [safari.__file__, '--data', str(self.f.source), '--crawl-date', day, '--prepare-only', *extra]
        with patch.object(sys, 'argv', argv), patch.object(safari, 'open_window', side_effect=AssertionError('Browser forbidden')), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return safari.main()

    def snapshot(self):
        return {p: p.read_bytes() for p in self.f.work.rglob('*') if p.is_file()}

    def test_dated_cache_cannot_bypass_manifest_with_other_date_or_award(self):
        self.assertEqual(self.prepare(), 0)
        cache = acm.crawl_path('cache', '2026-09-13')
        expected = acm.crawl_path('manifest', '2026-09-13')
        self.assertEqual(acm.manifest_path(cache, '2026-09-14', 'turing'), expected)
        self.f.write_input([fixtures.URL + 'changed'])
        before = self.snapshot()
        self.assertEqual(self.prepare('2026-09-14', '--award', 'turing', '--cache', str(cache)), 1)
        self.assertEqual(self.snapshot(), before)
        # Read-only comparisons must also reject a mislabelled capture date.
        argv = [compare.__file__, '--data', str(self.f.source), '--crawl-date', '2026-09-14', '--cache', str(cache)]
        with patch.object(sys, 'argv', argv), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(compare.main(), 1)
        self.assertEqual(self.snapshot(), before)

    def test_rejects_older_artifacts_even_without_manifest(self):
        for role in ('cache', 'report', 'state'):
            old = acm.crawl_path(role, '2026-09-12')
            old.parent.mkdir(exist_ok=True)
            old.write_text('{}')
            before = self.snapshot()
            self.assertEqual(self.prepare('2026-09-13', '--award', 'turing', '--' + role, str(old)), 1)
            self.assertEqual(self.snapshot(), before)

    def test_custom_crawl_outputs_and_input_cannot_be_overwritten(self):
        self.assertEqual(self.f.run_crawler('--prepare-only'), 0)
        before = self.snapshot()
        for protected in (self.f.cache, self.f.report, self.f.state, self.f.source):
            # Use an identical copy as input, so the old snapshot is not the
            # current invocation's --data and still needs ownership protection.
            copied = self.f.work / 'copy.csv'
            copied.write_bytes(self.f.source.read_bytes())
            baseline = self.snapshot()
            self.assertEqual(self.prepare('2026-09-14', '--data', str(copied), '--report', str(protected)), 1)
            self.assertEqual(self.snapshot(), baseline)
            copied.unlink()
        self.assertEqual(self.snapshot(), before)

    def test_resume_cannot_change_registered_report_or_state(self):
        self.assertEqual(self.f.run_crawler('--prepare-only'), 0)
        before = self.snapshot()
        for role in ('report', 'state'):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(self.f.run_crawler('--prepare-only', '--' + role, str(self.f.work / ('new-' + role + '.json'))), 1)
            self.assertEqual(self.snapshot(), before)

    def test_citation_excludes_press_release_but_preserves_substantive_links(self):
        # The trailing link reproduces the Frances Allen capture. Inline links
        # and formatting remain part of the citation in both award modes.
        citation = 'For <em>useful</em> <a href="/research">contributions.</a>\n<a href="/press-releases/award.pdf"><strong>press</strong> release</a>'
        for award, heading in acm.AWARD_HEADINGS.items():
            body = fixtures.HTML.replace('ACM Fellows', heading).replace('For useful contributions.', citation)
            self.assertEqual(acm.parse_profile_html(body, award)['citation'], 'For useful contributions.')

    def test_batch_cooldown_survives_limit_prepare_and_resume(self):
        self.f.write_input([fixtures.URL + str(i) for i in range(26)])
        good = safari.entry_from_html(fixtures.URL, fixtures.HTML)
        with patch.object(safari, 'open_window', return_value=123), patch.object(safari, 'close_window'), patch.object(safari, 'fetch_profile', return_value=good), patch.object(safari.time, 'time', return_value=1000), patch.object(safari.time, 'sleep') as sleep:
            self.assertEqual(self.f.run_crawler('--limit-new', '5'), 0)
            self.assertEqual(self.f.run_crawler('--limit-new', '20', '--batch-pause-jitter', '0'), 0)
            state = json.loads(self.f.state.read_text())
            self.assertEqual((state['batch_attempts'], state['cooldown_until']), (25, 1075))
            self.assertEqual(self.f.run_crawler('--prepare-only'), 0)
            self.assertEqual(self.f.run_crawler(), 0)
            self.assertEqual([c.args[0] for c in sleep.call_args_list if c.args[0] > 0], [75])
            self.assertEqual(json.loads(self.f.state.read_text())['batch_attempts'], 1)

    def test_interrupted_cooldown_resumes_only_remaining_wait(self):
        self.f.write_input([fixtures.URL, fixtures.URL + '2'])
        good = safari.entry_from_html(fixtures.URL, fixtures.HTML)
        def interrupt_cooldown(seconds):
            if seconds > 0:
                raise KeyboardInterrupt
        with patch.object(safari, 'open_window', return_value=123), patch.object(safari, 'close_window'), patch.object(safari, 'fetch_profile', return_value=good):
            with patch.object(safari.time, 'time', return_value=1000), patch.object(safari.time, 'sleep', side_effect=interrupt_cooldown):
                self.assertEqual(self.f.run_crawler('--batch-size', '1', '--batch-pause-jitter', '0'), 130)
            self.assertEqual(json.loads(self.f.state.read_text())['cooldown_until'], 1075)
            with patch.object(safari.time, 'time', return_value=1040), patch.object(safari.time, 'sleep') as sleep:
                self.assertEqual(self.f.run_crawler('--batch-size', '1'), 0)
                sleep.assert_called_once_with(35)

    def test_elapsed_cooldown_does_not_wait_again(self):
        self.f.write_input([fixtures.URL, fixtures.URL + '2'])
        good = safari.entry_from_html(fixtures.URL, fixtures.HTML)
        with patch.object(safari, 'open_window', return_value=123), patch.object(safari, 'close_window'), patch.object(safari, 'fetch_profile', return_value=good):
            with patch.object(safari.time, 'time', return_value=1000):
                self.assertEqual(self.f.run_crawler('--limit-new', '1', '--batch-size', '1', '--batch-pause-jitter', '0'), 0)
            with patch.object(safari.time, 'time', return_value=1100), patch.object(safari.time, 'sleep') as sleep:
                self.assertEqual(self.f.run_crawler('--batch-size', '1'), 0)
                sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
