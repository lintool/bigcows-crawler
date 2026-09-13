# Crawler Reference

Run examples from `bigcows-crawler` with Python 3.10 or newer.
`path/to/input.csv` is supplied by the consuming application.
See [README.md](README.md) for input columns and shared-cache usage.

## ACM Fellow Profile Crawler

`scripts/cache_acm_fellow_profiles_safari.py` is the recommended ACM crawler on macOS.
`scripts/cache_acm_fellow_profiles.py` supplies its parser, cache helpers, and
report builder; that module's legacy HTTP entry point remains for compatibility
but can encounter blocking. The retired ACM Playwright transport is not supported.
The Safari crawler controls a dedicated browser window through AppleScript and
caches the `acm_fellow_profile` URLs in the caller-supplied CSV:

```text
path/to/input.csv
```

The script:

- reads profile rows from the required `--data` input;
- extracts unique non-empty `acm_fellow_profile` URLs;
- navigates Safari through its native URL property and reads the complete HTML source;
- uses only the Python standard library and `/usr/bin/osascript` (no Playwright or WebDriver);
- fetches each ACM profile page conservatively;
- caches the complete fetched HTML page for reuse;
- parses the page name, ACM Fellows award heading, location, year, and citation when available;
- removes recognized honorifics and credentials from parsed names; unusual or repeated titles and duplicated name parts can remain and need review;
- compares parsed fields against the CSV row;
- writes a JSON cache and a JSON report;
- does not modify CSV files.

Start a new crawl with a date and an input snapshot, then repeat that command to
resume. Replace the example date with the crawl start date:

```bash
python3 scripts/cache_acm_fellow_profiles_safari.py --crawl-date 2026-09-14 --data path/to/input.csv --limit-new 5
python3 scripts/cache_acm_fellow_profiles_safari.py --crawl-date 2026-09-14 --data path/to/input.csv
python3 scripts/cache_acm_fellow_profiles_safari.py --crawl-date 2026-09-14 --data path/to/input.csv --retry-status http_error
```

Both ACM entry points require `--crawl-date YYYY-MM-DD`, including cache-only
runs and commands with explicit path overrides. The date must be a valid calendar
date and identifies the crawl's start date, not each page's fetch date. Keep it
unchanged when resuming across midnight. For a read-only comparison against a
completed crawl, use the separate command with any application's current CSV:

```bash
python3 scripts/compare_acm_fellow_profiles.py --crawl-date 2026-09-13 --data path/to/current.csv
```

`--refresh` refetches every selected URL. Successful fetches replace the cache entry;
failures preserve the previous successful HTML and attach the latest failed response
as `last_attempt`. Omit it
when resuming. Successful entries with HTML are reused; `blocked`, `timeout`, and
`url_error` entries (and incomplete `ok` entries) are retried automatically.
Other cached errors require `--retry-status STATUS` or `--refresh`.
Retry selection uses `last_attempt.status` when present, so a preserved successful
capture does not hide a failed refresh. A later successful fetch clears `last_attempt`.

For independent runs on the same date, override all of `--cache`, `--report`, and
`--state` with separate paths under `.cache/`. Each override affects only that
path; other paths retain the date-based defaults. To preserve the input and console
output, the caller can save `acm-fellow-profile-input-YYYY-MM-DD.csv` and
`acm-fellow-profile-log-YYYY-MM-DD.txt` under `.cache/`; these are not generated
automatically. Use the input snapshot as `--data` on resumes.

### Crawl manifests

On first invocation, both ACM crawlers create a manifest containing the start date,
input path and SHA-256 checksum, and initial artifact paths. Subsequent invocations
reject changed input contents, a different date, or a different cache path before
writing crawl artifacts or fetching. An identical input snapshot at another path is
allowed. Other applications should use the comparison command against shared captures,
or select a separate crawl for different fetch inputs.

The default manifest is `.cache/acm-fellow-profile-manifest-YYYY-MM-DD.json`.
With `--cache custom.json`, it is `custom.manifest.json` beside that cache. Keep the
manifest with its cache; do not delete it to bypass an input mismatch. When first
registering an older cache without a manifest, supply its original input snapshot;
the manifest also records `initial_cache_sha256`. That checksum describes registration
time, not subsequent fetches. Existing manifests are not rewritten on each run.

### Safari setup and lifecycle

Live fetching requires macOS, Safari, and an interactive desktop session. Approve
the macOS Automation prompt allowing your launching terminal/application to
control Safari. This uses native AppleScript URL/source properties; it does not
require Safari WebDriver, remote automation, JavaScript from Apple Events, a
browser extension, or a Python browser package.

The crawler opens a dedicated window, records its ID in the progress file, and
closes only that window when it exits. Keep its window/tab open and unchanged.
Other Safari windows are not navigated or closed. Each navigation first clears
the previous document to avoid capturing stale HTML. Unexpected redirects or
incomplete HTML are treated as fetch errors. The native Safari session and its
HTTP cache remain in use; a fresh local cache does not disable Safari caching.

### Pacing, validation, and progress

- `--delay 6 --delay-jitter 1`: wait 5–7 seconds between profiles.
- `--batch-size 25 --batch-pause 75 --batch-pause-jitter 15`: pause 60–90 seconds every 25 fetch attempts, including retries.
- `--max-retries 2 --backoff 120 --backoff-jitter 15`: at most three attempts per profile, with 120–135 then 240–255 seconds of backoff.
- `--timeout 30`: wait up to 30 seconds for the requested page's complete HTML.
- `--pilot-size 5`: check status, name compatibility, and supplied year for each of the first five fetched profiles in every invocation. `--pilot-size 0` disables this gate after independent validation.
- `--limit-new N`: cap distinct profiles fetched this invocation; retries count toward the batch size, not this cap.
- `--state PATH`: override `.cache/acm-fellow-profile-state-YYYY-MM-DD.json`; progress includes `crawl_date`.

Cache and report are saved after every attempt. Progress states are `running`,
`cooldown`, `backoff`, `paused`, `failed`, or `complete`. Completion means the
invocation finished, not that every input URL succeeded or every field matches.
Outside the pilot, nontransient errors such as `http_error` are recorded and the
run continues. Exit codes are 0 for completion, 1 for a paused/failed run, and
130 for interruption. Inspect `status_counts`, missing entries, and review
candidates even after exit code 0. Input, cache, report, and state paths must all
be distinct.

### Troubleshooting

- **Automation denied:** allow the launching app under macOS System Settings → Privacy & Security → Automation → Safari, then rerun.
- **Window closed:** rerun with the same cache/report paths; a new dedicated window is opened and successful pages are skipped.
- **Blocking persists:** the crawler backs off and pauses. Inspect the failed page/report before resuming; do not repeatedly restart or switch sessions to force progress.
- **Pilot mismatch:** the failed validation is saved and remains blocked on resume, even with `--pilot-size 0`. Inspect the HTML, then use `--retry-status validation_error` to refetch. To explicitly accept a verified name/year variant without fetching, pass `--accept-profile URL --limit-new 0`; the acceptance is recorded. Other pilot errors require retrying their saved status. No CSV changes are automatic.
- **Need to keep the Mac awake:** run the command with `caffeinate -i python3 ...`. Keep logs under `.cache/`; do not run another writer against the same cache, report, or state file.

Default cache path for the selected crawl date:

```text
.cache/acm-fellow-profile-cache-YYYY-MM-DD.json
```

Default report path for the selected crawl date:

```text
.cache/acm-fellow-profile-report-YYYY-MM-DD.json
```

The ACM cache is keyed by profile URL. Each value contains the full `html`, fetch metadata, and parsed fields such as:

```json
{
  "status": "ok",
  "status_code": null,
  "fetch_method": "safari-applescript",
  "final_url": "https://awards.acm.org/award-recipients/example",
  "title": "Fellow Name",
  "page_name": "Fellow Name",
  "award_heading": "ACM Fellows",
  "location": "USA",
  "year": "2022",
  "citation": "For contributions ...",
  "html": "<complete fetched HTML page>",
  "fetched_at": "YYYY-MM-DDTHH:MM:SSZ"
}
```

Safari cannot read HTTP response codes or headers. `status_code` is always `null`
for Safari entries; known 404 and block pages are detected from HTML. Retry-After
headers are unavailable, so retries use the conservative backoff described above.

Possible `status` values include:

- `ok`: page fetched and the ACM Fellows award section was parsed.
- `http_error`: an ACM 404 page was recognized in HTML (HTTP transports can also record actual HTTP errors).
- `blocked`: ACM returned a Cloudflare/interstitial-style page instead of profile content.
- `url_error`: AppleScript, browser-window, navigation, or loaded-URL validation failure.
- `timeout`: request timed out.
- `invalid_url`: URL is not HTTP/HTTPS.
- `validation_error`: a fetched pilot page failed name or year compatibility; its HTML is retained for review.
- `no_name`: page fetched but no page name was parsed.
- `no_fellow_award`: page fetched but no `ACM Fellows` award section was parsed.

### Reports and data review

`scripts/compare_acm_fellow_profiles.py` is the read-only audit command. It reparses
HTML and emits JSON to stdout, or to a new file with `--output PATH`. Existing output
files and original crawl artifacts cannot be overwritten. It never creates a cache,
changes a manifest, updates crawl progress, or opens a browser. A missing cache is
an error. The manifest date/cache path is checked when present, while a different
comparison input is allowed. `crawl_input_sha256: null` denotes an unregistered cache.

Comparison output includes all input rows, `status_counts` (including `blank_url`
and `missing`), `difference_counts`, `name_mismatch_count`, duplicate URL row indexes,
and unreferenced cached URLs. Row indexes start at 1 for the first data row, excluding
the header. Each captured row reports freshly parsed fields, exact CSV/page
differences, name compatibility, capture status, and the latest attempt status.
The command exits 0 when comparison succeeds even if differences exist; review the
report instead of treating exit 0 as agreement. The matcher handles Unicode accents
and spacing, and only treats a first name as an initial when it is abbreviated;
different spelled-out first names do not match solely on their first letter.

The following describes the crawler's own progress/comparison report:

The report compares the input with cached parsed fields; `--limit-new 0` does not
reparse HTML. It reports one entry per unique nonempty profile URL, using the
first input row for duplicate URLs. Blank URLs are omitted. `cached_profiles`
counts input URLs present in the cache, including failures; it is not a successful-page count.
URLs absent from the cache appear as `missing` in `entries` and `status_counts`,
but are excluded from `review_candidates`.

`review_candidates` contains cached errors, failed latest attempts, and failed field comparisons. Years
and locations are compared exactly, citations after whitespace normalization,
and names with a permissive compatibility heuristic. Compatible initials, added
name parts, and even some malformed names can pass. Missing optional comparison
fields in the input can also produce candidates. A small candidate count is not
an exhaustive list of textual differences or proof that profiles identify the
right people; inspect exact name differences and the stored HTML when auditing.

When applying results to application data, verify the person and award first.
Use `status: ok` entries as evidence, not as automatic replacements. Preserve
existing values when the source is blank, truncated, malformed, or otherwise less
accurate. Keep clean names and review substantive conflicts against corroborating
sources; a newer fetch date does not establish correctness. Record dataset-specific
decisions in the consuming application.

Fresh caches are separate files; there is no undated default or automatic latest
selection. An explicit cache override still requires the date. Crawl reports describe
the bound input snapshot; use the separate comparison command after CSV changes to
preserve the original report and progress records.

## DBLP Profile Crawler

`scripts/cache_dblp_profiles.py` caches the `dblp_profile` URLs in the caller-supplied CSV:

```text
path/to/input.csv
```

The script:

- reads profile rows from the required `--data` input;
- extracts unique non-empty `dblp_profile` URLs;
- fetches each DBLP profile page with plain Python `urllib`;
- caches the complete fetched HTML page for reuse;
- extracts the DBLP profile title from page metadata, `h1`, or `<title>`;
- compares the expected ACM fellow name against the DBLP title;
- writes a JSON cache and JSON report;
- does not modify CSV files.

Basic commands:

```bash
python scripts/cache_dblp_profiles.py --data path/to/input.csv --limit-new 0
python scripts/cache_dblp_profiles.py --data path/to/input.csv --limit-new 2
python scripts/cache_dblp_profiles.py --data path/to/input.csv
python scripts/cache_dblp_profiles.py --data path/to/input.csv --refresh
python scripts/cache_dblp_profiles.py --data path/to/input.csv --retry-status http_error --limit-new 3
python scripts/cache_dblp_profiles.py --data path/to/input.csv
```

Compile-check the script:

```bash
python -m py_compile scripts/cache_dblp_profiles.py
```

Default cache path:

```text
.cache/dblp-profile-cache.json
```

Default report path:

```text
.cache/dblp-profile-report.json
```

The DBLP cache is keyed by profile URL. Each value contains the full `html`, fetch metadata, and parsed fields such as:

```json
{
  "status": "ok",
  "status_code": 200,
  "title": "DBLP Profile Title",
  "html": "<complete fetched HTML page>",
  "fetched_at": "YYYY-MM-DDTHH:MM:SSZ"
}
```

Other possible `status` values include:

- `ok`: page fetched and a title was extracted.
- `http_error`: DBLP returned an HTTP error.
- `blocked`: fetched page appears to be a bot block/interstitial page.
- `url_error`: DNS/network/connection failure.
- `timeout`: request timed out.
- `invalid_url`: URL is not HTTP/HTTPS.
- `no_title`: page fetched but no usable title was found.

The report contains `review_candidates` for non-`ok` rows and title/name mismatches. Treat these as review candidates, not automatic CSV fixes. The title matcher is intentionally permissive because some DBLP author pages include fuller names than the ACM CSV.

Use `--retry-status STATUS` to retry cached entries with a specific status without refreshing the whole cache. This is useful for revisiting cached `http_error`, `blocked`, or transient failure entries.

## CSRankings Crawler

`scripts/cache_csrankings.py` downloads the CSRankings faculty CSV shards from GitHub and stores them in the repo-local cache. It treats `csrankings-x.csv` as the documented shard family:

```text
https://raw.githubusercontent.com/emeryberger/CSrankings/gh-pages/csrankings-{letter}.csv
```

The script:

- downloads `csrankings-a.csv` through `csrankings-z.csv` by default;
- caches raw CSV shards under `.cache/csrankings/`;
- validates the expected CSV header `name,affiliation,homepage,scholarid,orcid`;
- writes a JSON report;
- skips cached shards unless `--refresh` is passed;
- does not modify files under `data/`.

Basic commands:

```bash
python scripts/cache_csrankings.py --limit-new 0
python scripts/cache_csrankings.py --letters a,b
python scripts/cache_csrankings.py
python scripts/cache_csrankings.py --refresh
python scripts/cache_csrankings.py --cache-dir path/to/cache --report path/to/report.json
```

Compile-check the script:

```bash
python -m py_compile scripts/cache_csrankings.py
```

Default cache directory:

```text
.cache/csrankings/
```

Default report path:

```text
.cache/csrankings-report.json
```

The report contains:

- `generated_at`
- `source`
- `base_url`
- `cache_dir`
- `total_shards`
- `cached_shards`
- `status_counts`
- `entries`

Each entry includes the shard letter, source URL, cache path, status, status code, row count, and fetch timestamp when available. Possible `status` values include:

- `ok`: CSV was fetched or cached and has the expected header plus data rows.
- `missing`: shard has not been cached yet.
- `http_error`: GitHub returned an HTTP error.
- `url_error`: DNS/network/connection failure.
- `timeout`: request timed out.
- `bad_csv`: downloaded content could not be parsed as CSV.
- `bad_header`: downloaded content did not have the expected CSRankings header.
- `empty`: downloaded content had no data rows.

The CSRankings crawler defaults are:

- `--delay 0.5`
- `--delay-jitter 0.5`
- `--batch-size 10`
- `--batch-size-jitter 2`
- `--batch-pause 10.0`
- `--batch-pause-jitter 5.0`
- `--max-retries 2`
- `--backoff 5.0`
- `--backoff-jitter 2.0`
- `--limit-new N` caps uncached requests for one run.
- `--letters a,b,c` restricts the shard set for testing or targeted refreshes.

## Google Scholar Profile Crawler

`scripts/cache_google_scholar_profiles.py` validates the `google_scholar_profile` URLs in the caller-supplied CSV:

```text
path/to/input.csv
```

The script:

- reads profile rows from the required `--data` input;
- extracts unique non-empty `google_scholar_profile` URLs;
- canonicalizes Scholar URLs to `https://scholar.google.com/citations?user=...`;
- fetches each Scholar profile page conservatively;
- caches the complete fetched HTML page for reuse;
- treats cached fetchable entries without `html` as incomplete and refetchable;
- extracts the Scholar page title, affiliation, keyword interests, citation count, h-index, i10-index, and first citation year;
- compares the expected ACM fellow name against the Scholar title;
- writes a JSON cache and a JSON report;
- exports a profile CSV only when `--output` is supplied.

The script also still supports the older bundled `*-data.js` format via `--data`, but CSV input is recommended for new applications.

## Basic Commands

Run a no-network report rebuild from existing cache:

```bash
python scripts/cache_google_scholar_profiles.py --data path/to/input.csv --limit-new 0
```

Run or resume crawling with default pacing:

```bash
python scripts/cache_google_scholar_profiles.py --data path/to/input.csv
```

Force refetch of cached URLs:

```bash
python scripts/cache_google_scholar_profiles.py --data path/to/input.csv --refresh
```

Retry cached entries with a specific status:

```bash
python scripts/cache_google_scholar_profiles.py --data path/to/input.csv --retry-status blocked
python scripts/cache_google_scholar_profiles.py --data path/to/input.csv --retry-status http_error --limit-new 3
```

Use a custom input file:

```bash
python scripts/cache_google_scholar_profiles.py --data path/to/input.csv
```

Use a custom output file, or skip CSV output:

```bash
python scripts/cache_google_scholar_profiles.py --data path/to/input.csv --output path/to/google_scholar_profiles.csv
python scripts/cache_google_scholar_profiles.py --data path/to/input.csv --no-write-csv
```

Compile-check the script:

```bash
python -m py_compile scripts/cache_google_scholar_profiles.py
```

## Cache

The crawler uses repo-local cache files by default. From the repo root, the default cache path is:

```text
.cache/google-scholar-profile-cache.json
```

The cache is a JSON object keyed by Scholar profile URL. Each value contains fields such as:

```json
{
  "status": "ok",
  "status_code": 200,
  "title": "Scholar Profile Title",
  "affiliation": "Scholar profile affiliation",
  "interests": ["Keyword 1", "Keyword 2"],
  "citations": "12345",
  "h_index": "67",
  "i10_index": "89",
  "citations_since_5y_ago": "2345",
  "h_index_since_5y_ago": "45",
  "i10_index_since_5y_ago": "56",
  "first_citation_year": "2005",
  "citation_by_year": {"2005": 126, "2006": 148},
  "html": "<complete fetched HTML page>",
  "fetched_at": "YYYY-MM-DDTHH:MM:SSZ"
}
```

Other possible `status` values include:

- `ok`: page fetched and a title was extracted.
- `http_error`: Scholar returned an HTTP error, commonly 404.
- `url_error`: DNS/network/connection failure.
- `timeout`: request timed out.
- `invalid_url`: URL is not HTTP/HTTPS.
- `blocked`: fetched page appears to be a Google block/interstitial page.
- `no_title`: page fetched but no usable title was found.

The cache is intentionally idempotent:

- complete cached entries are reused unless explicitly refreshed or selected by retry status;
- pass `--refresh` to refetch cached URLs;
- interrupted runs can be resumed safely because the cache is written after every request.

The cache stores complete HTML, so it can become large. `.cache/` is local-only and ignored by Git. If `.cache/` is missing, the crawler creates it automatically when it writes the cache/report. A cache-only run with `--limit-new 0` creates an empty cache plus a report without downloading pages.

## Report

Default repo-local report path:

```text
.cache/google-scholar-profile-report.json
```

The report is derived from the input CSV plus the cache. It contains:

- `generated_at`
- `total_profiles`
- `cached_profiles`
- `html_cached_profiles`
- `incomplete_cached_profiles`
- `status_counts`
- `mismatch_count`
- `stats_profiles`
- `mismatches`
- `entries`

Each report entry includes:

- `index`: ACM Fellows CSV row number.
- `name`: expected ACM fellow name.
- `url`: Scholar profile URL.
- `acm_profile`: ACM Fellow profile URL.
- `status`: cache status for the Scholar URL.
- `title`: extracted Scholar profile title.
- `affiliation`: extracted Scholar profile affiliation.
- `interests`: extracted Scholar profile keyword interests as a JSON array.
- `citations`: all-time Scholar citations.
- `h_index`: all-time Scholar h-index.
- `i10_index`: all-time Scholar i10-index.
- `citations_since_5y_ago`: recent Scholar citations.
- `h_index_since_5y_ago`: recent Scholar h-index.
- `i10_index_since_5y_ago`: recent Scholar i10-index.
- `first_citation_year`: earliest year shown in Scholar's `Citations per year` chart.
- `citation_by_year`: JSON object mapping year strings to citation counts from Scholar's `Citations per year` chart.
- `match`: `true`, `false`, or `null`.
- `fetched_at`: cache timestamp, when available.

An explicitly requested Scholar output CSV is written in this column order:

```text
name,profile,crawl_date,affiliation,interests,citations,h_index,i10_index,citations_since_5y_ago,h_index_since_5y_ago,i10_index_since_5y_ago,first_citation_year,citation_by_year
```

The `interests` CSV cell is a JSON array string, not a semicolon-delimited list.
The `citation_by_year` CSV cell is a compact JSON object string.
The `*_since_5y_ago` columns correspond to Scholar's moving recent-window column, whose label changes over time.

Use report mismatches as review candidates, not automatic fixes. Some mismatches are harmless diacritic or formatting differences, such as `Urs Hoelzle` versus `Urs Hölzle`.

## Cool-Off Strategy

The crawler is deliberately slow:

- `--delay` defaults to `5.0` base seconds between uncached requests.
- `--delay-jitter` defaults to `2.0`; the actual delay is `delay + random(0, jitter)`.
- `--batch-size` defaults to `25` uncached requests.
- `--batch-size-jitter` defaults to `0`; each batch target is randomized by plus/minus that many requests and clamped to at least 1.
- `--batch-pause` defaults to `120.0` base seconds after each batch.
- `--batch-pause-jitter` defaults to `30.0`; the actual pause is `batch-pause + random(0, jitter)`.
- `--max-retries` defaults to `1` for transient failures.
- `--backoff` defaults to `10.0` seconds with exponential growth between retries.
- `--backoff-jitter` defaults to `5.0`; retry waits add `random(0, jitter)`.
- `--limit-new N` caps uncached requests for one run.
- `--retry-status STATUS` refetches cached entries with a specific status.

Google Scholar default behavior is therefore:

1. Fetch up to 25 uncached profiles.
2. Wait 5 to 7 seconds after each fetch.
3. Pause for 120 to 150 seconds after the batch.
4. Write cache and report after every request.

Because the Scholar crawler now requires full-page cache entries, older metadata-only entries are counted as `incomplete_cached_profiles` in the report and will be fetched again on a normal resume unless capped by `--limit-new`.

The recommended ACM Safari defaults and retry behavior are documented in
[Pacing, validation, and progress](#pacing-validation-and-progress). Its delay and
batch-pause jitter are symmetric (+/-), while retry jitter adds only positive time.
The legacy HTTP ACM entry point retains 25-profile batches with 60–90 second
pauses and a 2-second per-page delay; use Safari for current fetching.

The DBLP profile crawler uses plain HTTP by default and adds randomized pacing:

- `--delay` defaults to `2.0` base seconds between uncached requests.
- `--delay-jitter` defaults to `1.0`; the actual delay is `delay + random(0, jitter)`.
- `--batch-size` defaults to `50` uncached requests.
- `--batch-size-jitter` defaults to `5`; each batch target is randomized by plus/minus that many requests and clamped to at least 1.
- `--batch-pause` defaults to `60.0` base seconds after each batch.
- `--batch-pause-jitter` defaults to `15.0`; the actual pause is `batch-pause + random(0, jitter)`.
- `--max-retries` defaults to `2` for transient failures.
- `--backoff` defaults to `10.0` seconds with exponential growth between retries.
- `--backoff-jitter` defaults to `5.0`; retry waits add `random(0, jitter)`.
- `--limit-new N` caps uncached requests for one run.

If Google block markers appear while running the Scholar crawler, stop the run and resume later without `--refresh`.

## Google Scholar Block Detection

The script marks a fetched page as `blocked` when the page looks like a Google block/interstitial page. It checks for markers such as:

- `not a robot`
- `unusual traffic`
- `/sorry/`
- `our systems have detected unusual traffic`

Do not flag every occurrence of the word `captcha`: Scholar profile pages can legitimately contain paper titles with that word.

## Git Hygiene

Do not commit these generated artifacts:

```text
.cache/
scripts/__pycache__/
*.pyc
```

The repository `.gitignore` already excludes `.cache/` and Python bytecode.
