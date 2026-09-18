"""Scholar raw capture, recovery, and offline reprocessing checks."""

import contextlib
from email.message import Message
import hashlib
import importlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SCHOLAR = importlib.import_module("cache_google_scholar_profiles")
URL = "https://scholar.google.com/citations?user=example"
HTML = '<title>Example Person - Google Scholar</title><table id="gsc_rsb_st"><tr><td>Citations</td><td>123</td><td>12</td></tr></table>'


class Response(io.BytesIO):
    status = 200

    def __init__(self, raw, encoding="utf-8"):
        super().__init__(raw)
        self.headers = Message()
        self.headers["Content-Type"] = "text/html; charset=" + encoding

    def geturl(self):
        return URL + "&pagesize=100&cstart=0"


class ScholarCaptureTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.cache = self.work / "cache.json"
        self.report = self.work / "report.json"
        self.source = self.work / "people.csv"
        self.source.write_text("name,google_scholar_profile\nExample Person," + URL + "\n")

    def run_crawler(self, *extra):
        args = ["--data", self.source, "--cache", self.cache, "--report", self.report,
                "--delay", "0", "--delay-jitter", "0", "--backoff", "0", "--backoff-jitter", "0", *extra]
        with patch.object(sys, "argv", [SCHOLAR.__file__, *map(str, args)]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(SCHOLAR.main(), 0)
        return json.loads(self.cache.read_text())[URL]

    def store(self):
        return SCHOLAR.CaptureStore(self.cache)

    def test_exact_response_bytes_and_request_size_with_small_index(self):
        raw = HTML.replace("Person", "Pérson").encode("latin1") + b"\r\n<!--\x80-->"
        with patch.object(SCHOLAR.urllib.request, "urlopen", return_value=Response(raw, "iso-8859-1")) as fetch:
            entry = self.run_crawler()
        self.assertEqual(fetch.call_count, 1)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(fetch.call_args.args[0].full_url).query)
        self.assertEqual(query, {"user": ["example"], "pagesize": ["100"], "cstart": ["0"]})
        self.assertNotIn("html", entry)
        self.assertNotIn("_raw_body", entry)
        self.assertEqual((self.work / entry["html_path"]).read_bytes(), raw)
        self.assertEqual(entry["html_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(entry["html_bytes"], len(raw))
        self.assertEqual(entry["title"], "Example Pérson")
        capture = self.store().manifest["captures"][0]
        self.assertEqual(capture["pagesize"], 100)
        self.assertEqual(capture["cstart"], 0)
        self.assertEqual(capture["status_code"], 200)
        self.assertEqual(capture["body_source"], "http-response-bytes")
        self.assertIn("Content-Type", capture["response_headers"])
        self.assertNotIn("citations", capture)

    def test_legacy_migration_is_offline_idempotent_and_keeps_failure(self):
        self.cache.write_text(json.dumps({URL: {
            "status": "ok", "html": HTML, "fetched_at": "2020-01-01T00:00:00Z",
            "last_fetch_error": {"status": "timeout", "fetched_at": "2020-01-02T00:00:00Z"},
        }}))
        with patch.object(SCHOLAR.urllib.request, "urlopen", side_effect=AssertionError("network")):
            first = self.run_crawler("--limit-new", "0")
            second = self.run_crawler()
        self.assertEqual(first, second)
        self.assertEqual(first["citations"], "123")
        self.assertEqual(first["pagesize"], 20)
        self.assertEqual(first["body_source"], "legacy-decoded-html")
        self.assertEqual(first["fetched_at"], "2020-01-01T00:00:00Z")
        self.assertEqual(first["last_fetch_error"]["status"], "timeout")
        self.assertEqual(len(self.store().manifest["captures"]), 2)
        self.assertEqual((self.work / first["html_path"]).read_text(), HTML)

    def test_refresh_retains_history_and_all_failed_refresh_types(self):
        with patch.object(SCHOLAR.urllib.request, "urlopen", return_value=Response(HTML.encode())):
            good = self.run_crawler()
        headers = Message()
        for response in (
            Response(b"<title>Sorry</title>unusual traffic"),
            Response(b"no title"),
            urllib.error.HTTPError(URL, 404, "missing", headers, io.BytesIO(b"not found")),
            TimeoutError(),
        ):
            kwargs = {"side_effect": response} if isinstance(response, Exception) else {"return_value": response}
            with patch.object(SCHOLAR.urllib.request, "urlopen", **kwargs):
                entry = self.run_crawler("--refresh", "--max-retries", "0")
            self.assertEqual(entry["capture_id"], good["capture_id"])
            self.assertEqual(entry["citations"], "123")
            self.assertIn("last_fetch_error", entry)
            self.assertEqual(json.loads(self.report.read_text())["entries"][0]["last_fetch_error"], entry["last_fetch_error"])
        with patch.object(SCHOLAR.urllib.request, "urlopen", return_value=Response(HTML.replace("123", "456").encode())):
            fresh = self.run_crawler("--refresh")
        self.assertNotEqual(fresh["html_path"], good["html_path"])
        self.assertNotIn("last_fetch_error", fresh)
        self.assertEqual((self.work / good["html_path"]).read_text(), HTML)
        self.assertEqual(len(self.store().manifest["captures"]), 6)

    def test_retries_archive_error_bytes_and_success_separately(self):
        raw = b"<html>busy\xff</html>"
        error = urllib.error.HTTPError(URL, 503, "busy", Message(), io.BytesIO(raw))
        with patch.object(SCHOLAR.urllib.request, "urlopen", side_effect=[error, Response(HTML.encode())]) as fetch:
            entry = self.run_crawler()
        captures = self.store().manifest["captures"]
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(len(captures), 2)
        self.assertEqual((self.work / captures[0]["html_path"]).read_bytes(), raw)
        self.assertEqual(captures[0]["status_code"], 503)
        self.assertEqual(entry["status"], "ok")
        self.assertEqual(entry["attempts"], 2)

    def test_rebuild_uses_current_parser_and_ignores_broken_derived_cache(self):
        with patch.object(SCHOLAR.urllib.request, "urlopen", return_value=Response(HTML.encode())):
            entry = self.run_crawler()
        manifest_before = self.store().manifest_path.read_bytes()
        raw_before = (self.work / entry["html_path"]).read_bytes()
        self.cache.write_text("broken derived cache")
        original = SCHOLAR.parse_profile_html
        def changed_parser(body):
            parsed = original(body)
            parsed["citations"] = "999"
            return parsed
        with patch.object(SCHOLAR.urllib.request, "urlopen", side_effect=AssertionError("network")), patch.object(SCHOLAR, "parse_profile_html", side_effect=changed_parser):
            rebuilt = self.run_crawler("--rebuild-cache", "--output", self.work / "export.csv")
        self.assertEqual(rebuilt["citations"], "999")
        self.assertIn("999", (self.work / "export.csv").read_text())
        self.assertEqual(self.store().manifest_path.read_bytes(), manifest_before)
        self.assertEqual((self.work / entry["html_path"]).read_bytes(), raw_before)

    def test_manifest_recovers_interrupted_cache_write_without_refetch(self):
        with patch.object(SCHOLAR.urllib.request, "urlopen", return_value=Response(HTML.encode())):
            SCHOLAR.fetch_profile(URL, 0, 0, 0, capture_store=self.store())
        self.assertFalse(self.cache.exists())
        with patch.object(SCHOLAR.urllib.request, "urlopen", side_effect=AssertionError("network")):
            entry = self.run_crawler()
        self.assertEqual(entry["citations"], "123")
        self.assertEqual(len(self.store().manifest["captures"]), 1)

    def test_interrupted_migration_does_not_reorder_or_duplicate_history(self):
        legacy = {URL: {"status": "ok", "html": HTML, "fetched_at": "2020-01-01T00:00:00Z"}}
        self.cache.write_text(json.dumps(legacy))
        store = self.store()
        store.migrate(json.loads(self.cache.read_text()))
        with patch.object(SCHOLAR.urllib.request, "urlopen", return_value=Response(HTML.replace("123", "456").encode())):
            SCHOLAR.fetch_profile(URL, 0, 0, 0, capture_store=store)
        # The cache still contains the old embedded HTML after an interruption.
        with patch.object(SCHOLAR.urllib.request, "urlopen", side_effect=AssertionError("network")):
            recovered = self.run_crawler()
        self.assertEqual(recovered["citations"], "456")
        self.assertEqual(len(self.store().manifest["captures"]), 2)

    def test_migration_recovers_body_written_before_manifest_failure(self):
        legacy = {URL: {"status": "ok", "html": HTML, "fetched_at": "2020-01-01T00:00:00Z"}}
        self.cache.write_text(json.dumps(legacy))
        with patch.object(SCHOLAR, "atomic_write_json", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                self.store().migrate(json.loads(self.cache.read_text()))
        with patch.object(SCHOLAR.urllib.request, "urlopen", side_effect=AssertionError("network")):
            recovered = self.run_crawler()
        self.assertEqual(recovered["citations"], "123")
        self.assertEqual(len(self.store().manifest["captures"]), 1)
        self.assertEqual(len(list(self.store().root.rglob("*.html"))), 1)

    def test_parser_failure_preserves_raw_body_for_later_reprocessing(self):
        with patch.object(SCHOLAR.urllib.request, "urlopen", return_value=Response(HTML.encode())), patch.object(SCHOLAR, "parse_profile_html", side_effect=ValueError("parser bug")):
            failed = self.run_crawler()
        self.assertEqual(failed["status"], "parse_error")
        self.assertEqual((self.work / failed["html_path"]).read_bytes(), HTML.encode())
        with patch.object(SCHOLAR.urllib.request, "urlopen", side_effect=AssertionError("network")):
            reparsed = self.run_crawler("--rebuild-cache")
        self.assertEqual(reparsed["status"], "ok")
        self.assertEqual(reparsed["citations"], "123")
        self.assertEqual(reparsed["capture_id"], failed["capture_id"])

    def test_missing_or_corrupt_capture_is_reported_and_refetched_on_resume(self):
        for corruption in ("missing", "modified"):
            with self.subTest(corruption=corruption):
                with patch.object(SCHOLAR.urllib.request, "urlopen", return_value=Response(HTML.encode())):
                    good = self.run_crawler("--refresh")
                path = self.work / good["html_path"]
                if corruption == "missing":
                    path.unlink()
                else:
                    path.write_bytes(b"altered")
                with patch.object(SCHOLAR.urllib.request, "urlopen", side_effect=AssertionError("network")), contextlib.redirect_stderr(io.StringIO()):
                    entry = self.run_crawler("--limit-new", "0")
                self.assertIn("html_error", entry)
                self.assertEqual(json.loads(self.report.read_text())["incomplete_cached_profiles"], 1)
                with patch.object(SCHOLAR.urllib.request, "urlopen", return_value=Response(HTML.encode())) as fetch, contextlib.redirect_stderr(io.StringIO()):
                    fixed = self.run_crawler()
                self.assertEqual(fetch.call_count, 1)
                self.assertNotIn("html_error", fixed)

    def test_page_size_option_does_not_force_refresh(self):
        with patch.object(SCHOLAR.urllib.request, "urlopen", return_value=Response(HTML.encode())) as fetch:
            first = self.run_crawler("--page-size", "20")
        self.assertIn("pagesize=20", fetch.call_args.args[0].full_url)
        with patch.object(SCHOLAR.urllib.request, "urlopen", side_effect=AssertionError("network")):
            resumed = self.run_crawler()
        self.assertEqual(first["capture_id"], resumed["capture_id"])
        self.assertEqual(resumed["pagesize"], 20)

    def test_rebuild_requires_manifest_and_rejects_network_options(self):
        with self.assertRaisesRegex(ValueError, "Cannot rebuild without"):
            self.run_crawler("--rebuild-cache")
        self.assertFalse(self.cache.exists())
        for option in (("--refresh",), ("--retry-status", "blocked")):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                self.run_crawler("--rebuild-cache", *option)

    def test_interrupted_retries_resume_even_with_previous_success(self):
        cases = ("429", "503", "timeout", "url_error")
        for previous_success in (False, True):
            for failure in cases:
                with self.subTest(previous_success=previous_success, failure=failure):
                    self.cache = self.work / f"retry-{previous_success}-{failure}.json"
                    if previous_success:
                        with patch.object(SCHOLAR.urllib.request, "urlopen", return_value=Response(HTML.encode())):
                            self.run_crawler()
                    if failure.isdigit():
                        error = urllib.error.HTTPError(URL, int(failure), "busy", Message(), io.BytesIO(b"busy"))
                    elif failure == "timeout":
                        error = TimeoutError()
                    else:
                        error = urllib.error.URLError("offline")
                    with patch.object(SCHOLAR.urllib.request, "urlopen", side_effect=error), patch.object(SCHOLAR.time, "sleep", side_effect=KeyboardInterrupt):
                        with self.assertRaises(KeyboardInterrupt):
                            self.run_crawler("--refresh")
                    interrupted = self.store().manifest["captures"][-1]
                    self.assertTrue(interrupted["retry_pending"])
                    with patch.object(SCHOLAR.urllib.request, "urlopen", side_effect=AssertionError("network")):
                        self.run_crawler("--limit-new", "0")
                    self.assertTrue(json.loads(self.report.read_text())["entries"][0]["retry_pending"])
                    with patch.object(SCHOLAR.urllib.request, "urlopen", return_value=Response(HTML.encode())) as fetch:
                        recovered = self.run_crawler()
                    self.assertEqual(fetch.call_count, 1)
                    self.assertEqual(recovered["status"], "ok")
                    self.assertFalse(recovered["retry_pending"])
                    self.assertNotIn("last_fetch_error", recovered)
                    with patch.object(SCHOLAR.urllib.request, "urlopen", side_effect=AssertionError("network")):
                        self.run_crawler()

    def test_exhausted_retry_sequences_remain_cached(self):
        for previous_success in (False, True):
            for failure in ("503", "timeout"):
                with self.subTest(previous_success=previous_success, failure=failure):
                    self.cache = self.work / f"exhausted-{previous_success}-{failure}.json"
                    if previous_success:
                        with patch.object(SCHOLAR.urllib.request, "urlopen", return_value=Response(HTML.encode())):
                            self.run_crawler()
                    errors = [
                        TimeoutError() if failure == "timeout" else
                        urllib.error.HTTPError(URL, 503, "busy", Message(), io.BytesIO(b"busy"))
                        for _ in range(2)
                    ]
                    with patch.object(SCHOLAR.urllib.request, "urlopen", side_effect=errors) as fetch:
                        self.run_crawler("--refresh")
                    self.assertEqual(fetch.call_count, 2)
                    self.assertFalse(self.store().manifest["captures"][-1]["retry_pending"])
                    with patch.object(SCHOLAR.urllib.request, "urlopen", side_effect=AssertionError("network")):
                        self.run_crawler()

    def test_parser_failures_do_not_block_other_profiles_or_reports(self):
        bad_html = HTML + "<!-- bad capture -->"
        good_url, new_url = URL + "2", URL + "3"
        self.source.write_text("name,google_scholar_profile\nExample Person," + URL +
                               "\nExample Person," + good_url + "\nExample Person," + new_url + "\n")
        for stored_status in ("ok", "parse_error"):
            self.cache = self.work / f"isolated-{stored_status}.json"
            store = self.store()
            bad = store.save(URL, {"status": stored_status, "html": bad_html})
            store.save(good_url, {"status": "ok", "html": HTML})
            original_parser = SCHOLAR.parse_profile_html
            def failing_parser(body):
                if "bad capture" in body:
                    raise ValueError("bad capture")
                return original_parser(body)
            with patch.object(SCHOLAR, "parse_profile_html", side_effect=failing_parser), contextlib.redirect_stderr(io.StringIO()):
                for mode in (("--limit-new", "0"), ("--rebuild-cache",)):
                    with patch.object(SCHOLAR.urllib.request, "urlopen", side_effect=AssertionError("network")):
                        entry = self.run_crawler(*mode)
                    self.assertEqual(entry["status"], "parse_error")
                    self.assertEqual(entry["error"], "ValueError: bad capture")
                    self.assertEqual(json.loads(self.cache.read_text())[good_url]["citations"], "123")
                    report = json.loads(self.report.read_text())
                    self.assertEqual(report["status_counts"], {"parse_error": 1, "ok": 1, "missing": 1})
                    self.assertEqual(report["entries"][0]["error"], "ValueError: bad capture")
                with patch.object(SCHOLAR.urllib.request, "urlopen", return_value=Response(HTML.encode())) as fetch:
                    self.run_crawler()
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(json.loads(self.cache.read_text())[new_url]["status"], "ok")
            self.assertEqual((self.work / bad["html_path"]).read_text(), bad_html)

    def test_replay_recovers_parse_error_before_later_failure_selection(self):
        store = self.store()
        store.save(URL, {"status": "ok", "html": HTML.replace("123", "100")})
        recovered_capture = store.save(URL, {"status": "parse_error", "error": "old parser bug", "html": HTML})
        failure = store.save(URL, {"status": "timeout", "retry_pending": False})
        manifest_before = store.manifest_path.read_bytes()
        with patch.object(SCHOLAR.urllib.request, "urlopen", side_effect=AssertionError("network")):
            for mode in (("--rebuild-cache",), ()):
                entry = self.run_crawler(*mode)
                self.assertEqual(entry["status"], "ok")
                self.assertEqual(entry["citations"], "123")
                self.assertEqual(entry["capture_id"], recovered_capture["capture_id"])
                self.assertNotIn("error", entry)
                self.assertEqual(entry["last_fetch_error"]["capture_id"], failure["capture_id"])
        self.assertEqual(store.manifest_path.read_bytes(), manifest_before)

    def test_zero_byte_responses_are_retained_but_refetched(self):
        for http_error in (False, True):
            with self.subTest(http_error=http_error):
                self.cache = self.work / f"empty-{http_error}.json"
                kwargs = (
                    {"side_effect": urllib.error.HTTPError(URL, 404, "missing", Message(), io.BytesIO(b""))}
                    if http_error else {"return_value": Response(b"")}
                )
                with patch.object(SCHOLAR.urllib.request, "urlopen", **kwargs):
                    empty = self.run_crawler()
                self.assertEqual((self.work / empty["html_path"]).read_bytes(), b"")
                self.assertEqual(empty["html_bytes"], 0)
                with patch.object(SCHOLAR.urllib.request, "urlopen", side_effect=AssertionError("network")):
                    self.run_crawler("--limit-new", "0")
                report = json.loads(self.report.read_text())
                self.assertEqual(report["html_cached_profiles"], 0)
                self.assertEqual(report["incomplete_cached_profiles"], 1)
                with patch.object(SCHOLAR.urllib.request, "urlopen", return_value=Response(HTML.encode())) as fetch:
                    recovered = self.run_crawler()
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(recovered["status"], "ok")
                self.assertEqual(len(self.store().manifest["captures"]), 2)

    def test_no_title_capture_recovers_with_or_without_later_timeout(self):
        for later_timeout in (False, True):
            with self.subTest(later_timeout=later_timeout):
                self.cache = self.work / f"no-title-{later_timeout}.json"
                store = self.store()
                capture = store.save(URL, {"status": "no_title", "status_code": 200, "html": HTML})
                if later_timeout:
                    failure = store.save(URL, {"status": "timeout", "retry_pending": False})
                manifest_before = store.manifest_path.read_bytes()
                with patch.object(SCHOLAR.urllib.request, "urlopen", side_effect=AssertionError("network")):
                    for mode in (("--rebuild-cache",), ()):
                        entry = self.run_crawler(*mode)
                        self.assertEqual(entry["status"], "ok")
                        self.assertEqual(entry["title"], "Example Person")
                        self.assertEqual(entry["citations"], "123")
                        self.assertEqual(entry["capture_id"], capture["capture_id"])
                        if later_timeout:
                            self.assertEqual(entry["last_fetch_error"]["capture_id"], failure["capture_id"])
                        else:
                            self.assertNotIn("last_fetch_error", entry)
                self.assertEqual(store.manifest_path.read_bytes(), manifest_before)
                self.assertEqual((self.work / capture["html_path"]).read_text(), HTML)

    def test_enrichment_reclassifies_legacy_no_title_html(self):
        cache = {URL: {"status": "no_title", "html": HTML}}
        SCHOLAR.enrich_cache_from_html(cache)
        self.assertEqual(cache[URL]["status"], "ok")
        self.assertEqual(cache[URL]["title"], "Example Person")

    def test_replay_preserves_http_failures_and_checks_block_markers(self):
        cases = (
            ("http_error", 403, HTML, "http_error"),
            ("parse_error", 503, HTML, "parse_error"),
            ("no_title", 200, HTML + "unusual traffic", "blocked"),
            ("blocked", 200, HTML + "unusual traffic", "blocked"),
            ("ok", 200, HTML + "unusual traffic", "blocked"),
            ("no_title", 200, "<html>Still no name</html>", "no_title"),
        )
        for index, (status, code, body, expected) in enumerate(cases):
            with self.subTest(status=status, code=code):
                self.cache = self.work / f"classified-{index}.json"
                self.store().save(URL, {"status": status, "status_code": code, "html": body})
                with patch.object(SCHOLAR.urllib.request, "urlopen", side_effect=AssertionError("network")):
                    entry = self.run_crawler("--rebuild-cache")
                self.assertEqual(entry["status"], expected)

    def test_http_failure_remains_failed_after_parser_exception_and_recovery(self):
        self.store().save(URL, {"status": "http_error", "status_code": 503, "html": HTML})
        with patch.object(SCHOLAR.urllib.request, "urlopen", side_effect=AssertionError("network")):
            with patch.object(SCHOLAR, "parse_profile_html", side_effect=ValueError("parser bug")), contextlib.redirect_stderr(io.StringIO()):
                failed = self.run_crawler("--rebuild-cache")
            self.assertEqual(failed["status"], "http_error")
            repaired_parser = self.run_crawler("--rebuild-cache")
            self.assertEqual(repaired_parser["status"], "http_error")


if __name__ == "__main__":
    unittest.main()
