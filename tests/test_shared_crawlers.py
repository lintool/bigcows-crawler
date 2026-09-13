"""Offline integration checks for application inputs and shared cache reuse."""

import contextlib
import csv
import importlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
ACM = importlib.import_module("cache_acm_fellow_profiles")
DBLP = importlib.import_module("cache_dblp_profiles")
SCHOLAR = importlib.import_module("cache_google_scholar_profiles")
SAFARI = importlib.import_module("cache_acm_fellow_profiles_safari")
CSRANKINGS = importlib.import_module("cache_csrankings")


class SharedCrawlerTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)

    def input_csv(self, name, column, urls):
        path = self.work / name
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["name", column])
            writer.writeheader()
            for url in urls:
                writer.writerow({"name": "Example Person", column: url})
        return path

    def run_crawler(self, module, *args):
        with patch.object(sys, "argv", [module.__file__, *map(str, args)]):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(module.main(), 0)

    def test_profile_inputs_required_and_help_works_outside_repository(self):
        for module in (ACM, DBLP, SCHOLAR, SAFARI):
            with self.subTest(module=module.__name__):
                result = subprocess.run(
                    [sys.executable, "-B", module.__file__], cwd=self.work,
                    text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("--data", result.stderr)
        for module in (ACM, DBLP, SCHOLAR, SAFARI, CSRANKINGS):
            result = subprocess.run(
                [sys.executable, "-B", module.__file__, "--help"],
                cwd=self.work, text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_defaults_belong_to_crawler_repository(self):
        for module in (ACM, DBLP, SCHOLAR, SAFARI, CSRANKINGS):
            argv = [module.__file__]
            if module is not CSRANKINGS:
                argv += ["--data", str(self.work / "app.csv")]
            if module in (ACM, SAFARI):
                argv += ["--crawl-date", "2026-09-13"]
            with patch.object(sys, "argv", argv):
                args = module.parse_args()
            self.assertTrue(args.report.is_relative_to(ROOT / ".cache"))
            cache = args.cache_dir if module is CSRANKINGS else args.cache
            self.assertTrue(cache.is_relative_to(ROOT / ".cache"))
            if module is SCHOLAR:
                self.assertIsNone(args.output)
            if module is SAFARI:
                self.assertEqual(args.cache, ACM.crawl_path("cache", "2026-09-13"))

    def test_two_applications_reuse_profiles_and_preserve_other_cached_urls(self):
        cases = [
            (DBLP, "dblp_profile", "https://dblp.org/pid/example"),
            (SCHOLAR, "google_scholar_profile", "https://scholar.google.com/citations?user=example"),
        ]
        for module, column, url in cases:
            with self.subTest(module=module.__name__):
                first = self.input_csv("first.csv", column, [url, url, ""])
                second = self.input_csv("second.csv", column, [url, url + "2"])
                before = first.read_bytes(), second.read_bytes()
                cache = self.work / (module.__name__ + ".json")
                report = self.work / "report.json"
                common = ["--cache", cache, "--report", report, "--delay", "0"]
                if module is not ACM:
                    common += ["--delay-jitter", "0"]
                entry = {
                    "status": "ok", "status_code": 200, "title": "Example Person",
                    "page_name": "Example Person", "award_heading": "ACM Fellows",
                    "html": "<h1>Example Person</h1>", "fetched_at": "2026-09-13T00:00:00Z",
                }
                fetch_name = "fetch_profile"
                with patch.object(module, fetch_name, return_value=entry.copy()) as fetch:
                    self.run_crawler(module, "--data", first, *common)
                    self.assertEqual(fetch.call_count, 1)
                    self.run_crawler(module, "--data", second, *common)
                    self.assertEqual(fetch.call_count, 2)
                    self.assertEqual(fetch.call_args.args[0], url + "2")
                self.assertEqual(set(json.loads(cache.read_text())), {url, url + "2"})
                self.assertEqual(json.loads(report.read_text())["total_profiles"], 2)
                self.assertEqual((first.read_bytes(), second.read_bytes()), before)

    def test_acm_requires_a_valid_date_even_with_path_overrides(self):
        for module in (ACM, SAFARI):
            for value in (None, "2026-02-30", "20260913", "2026-9-13", "../cache"):
                argv = [module.__file__, "--data", "input.csv", "--cache", "custom.json"]
                if value is not None:
                    argv += ["--crawl-date", value]
                with self.subTest(module=module.__name__, date=value), patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        module.parse_args()
                    self.assertEqual(error.exception.code, 2)

    def test_acm_dates_isolate_runs_and_preserve_explicit_overrides(self):
        for module in (ACM, SAFARI):
            for day in ("2026-09-13", "2026-09-14", "2024-02-29"):
                argv = [module.__file__, "--data", "input.csv", "--crawl-date", day]
                with patch.object(sys, "argv", argv):
                    args = module.parse_args()
                self.assertEqual(args.cache, ROOT / ".cache" / f"acm-fellow-profile-cache-{day}.json")
                self.assertEqual(args.report, ROOT / ".cache" / f"acm-fellow-profile-report-{day}.json")
                if module is SAFARI:
                    self.assertEqual(args.state, ROOT / ".cache" / f"acm-fellow-profile-state-{day}.json")
                overrides = ["--cache", "custom-cache.json", "--report", "custom-report.json"]
                if module is SAFARI:
                    overrides += ["--state", "custom-state.json"]
                with patch.object(sys, "argv", argv + overrides):
                    custom = module.parse_args()
                self.assertEqual(custom.cache, Path("custom-cache.json"))
                self.assertEqual(custom.report, Path("custom-report.json"))
                if module is SAFARI:
                    self.assertEqual(custom.state, Path("custom-state.json"))

    def test_scholar_export_is_explicit_and_can_be_suppressed(self):
        url = "https://scholar.google.com/citations?user=example"
        source = self.input_csv("people.csv", "google_scholar_profile", [url])
        cache, report, output = (self.work / name for name in ("cache.json", "report.json", "export.csv"))
        cache.write_text(json.dumps({url: {
            "status": "ok", "title": "Example Person",
            "html": '<div id="gsc_prf_in">Example Person</div><table id="gsc_rsb_st"><tr><td>Citations</td><td>123</td><td>12</td></tr></table>',
            "citations": "123", "fetched_at": "2026-09-13T00:00:00Z",
        }}))
        args = ["--data", source, "--cache", cache, "--report", report, "--limit-new", "0"]
        with patch.object(SCHOLAR, "fetch_profile", side_effect=AssertionError("Unexpected network request")):
            self.run_crawler(SCHOLAR, *args)
            self.assertEqual(set(self.work.glob("*.csv")), {source})
            self.run_crawler(SCHOLAR, *args, "--output", output, "--no-write-csv")
            self.assertFalse(output.exists())
            self.run_crawler(SCHOLAR, *args, "--output", output)
        with output.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]["profile"], url)
        self.assertEqual(rows[0]["citations"], "123")
        self.assertNotIn(b"\r\n", output.read_bytes())

    def test_csrankings_reuses_cached_shards(self):
        cache = self.work / "shards"
        cache.mkdir()
        shard = cache / "csrankings-a.csv"
        content = "name,affiliation,homepage,scholarid,orcid\nExample Person,University,https://example.org,example,\n"
        shard.write_text(content)
        report = self.work / "report.json"
        with patch.object(CSRANKINGS, "fetch_shard", side_effect=AssertionError("Unexpected network request")):
            self.run_crawler(CSRANKINGS, "--cache-dir", cache, "--report", report, "--letters", "a")
        self.assertEqual(shard.read_text(), content)
        self.assertEqual(json.loads(report.read_text())["cached_shards"], 1)


if __name__ == "__main__":
    unittest.main()
