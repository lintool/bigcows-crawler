# Crawler Reference

Run examples from `bigcows-crawler` with Python 3.10 or newer.
`path/to/input.csv` is supplied by the consuming application.
See [README.md](README.md) for input columns and shared-cache usage.

## ACM Fellow Profile Crawler

`scripts/cache_acm_fellow_profiles.py` caches the `acm_fellow_profile` URLs in the caller-supplied CSV:

```text
path/to/input.csv
```

The script:

- reads profile rows from the required `--data` input;
- extracts unique non-empty `acm_fellow_profile` URLs;
- fetches each ACM profile page conservatively;
- caches the complete fetched HTML page for reuse;
- parses the page name, ACM Fellows award heading, location, year, and citation when available;
- normalizes parsed page names by removing leading honorifics such as `Dr.`, `Prof.`, `Professor`, and trailing credentials such as `PhD` / `Ph.D.`;
- compares parsed fields against the CSV row;
- writes a JSON cache and a JSON report;
- does not modify CSV files.

Basic commands:

```bash
python scripts/cache_acm_fellow_profiles.py --data path/to/input.csv --limit-new 0
python scripts/cache_acm_fellow_profiles.py --data path/to/input.csv
python scripts/cache_acm_fellow_profiles.py --data path/to/input.csv --refresh
python scripts/cache_acm_fellow_profiles.py --data path/to/input.csv
```

Compile-check the script:

```bash
python -m py_compile scripts/cache_acm_fellow_profiles.py
```

Default cache path:

```text
.cache/acm-fellow-profile-cache.json
```

Default report path:

```text
.cache/acm-fellow-profile-report.json
```

The ACM cache is keyed by profile URL. Each value contains the full `html`, fetch metadata, and parsed fields such as:

```json
{
  "status": "ok",
  "status_code": 200,
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

Other possible `status` values include:

- `ok`: page fetched and the ACM Fellows award section was parsed.
- `http_error`: ACM returned an HTTP error.
- `blocked`: ACM returned a Cloudflare/interstitial-style page instead of profile content.
- `url_error`: DNS/network/connection failure.
- `timeout`: request timed out.
- `invalid_url`: URL is not HTTP/HTTPS.
- `no_name`: page fetched but no page name was parsed.
- `no_fellow_award`: page fetched but no `ACM Fellows` award section was parsed.

The report contains `review_candidates` for rows where the page did not parse cleanly, or parsed name/year/location/citation differs from the CSV. Treat these as review candidates, not automatic CSV fixes.

When propagating ACM crawl results into `path/to/input.csv`, use only entries whose `status` is `ok`, and do not overwrite existing CSV values with blank parsed fields. The crawled page is newer than the original CSV for `name`, `year`, `location`, and `citation`, but parsed names must remain clean names as described above.

Historical ACM profile crawl notes (April 2026):

- The 2026-04-29 browser/CDP retry resolved all previously cached `blocked` pages.
- The current report has 1,628 `ok` entries, 0 `blocked` entries, and 11 `http_error` entries.
- The 11 `http_error` entries are ACM 404 pages. They are documented in the consuming application's data notes.

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

## ACM Fellow Playwright Crawler

`scripts/cache_acm_fellow_profiles_playwright.py` is a browser-backed companion to `scripts/cache_acm_fellow_profiles.py`. Use it when direct Python requests return `blocked` pages but the public ACM profile page works in a browser.

It uses the same input CSV, cache, report, parser, and report builder:

```text
path/to/input.csv
.cache/acm-fellow-profile-cache.json
.cache/acm-fellow-profile-report.json
```

Basic commands:

```bash
python scripts/cache_acm_fellow_profiles_playwright.py --data path/to/input.csv --limit-new 2
python scripts/cache_acm_fellow_profiles_playwright.py --data path/to/input.csv --retry-status blocked --limit-new 2
python scripts/cache_acm_fellow_profiles_playwright.py --data path/to/input.csv --headed --retry-status blocked --limit-new 2
python scripts/cache_acm_fellow_profiles_playwright.py --data path/to/input.csv --headed --channel chrome --retry-status blocked --limit-new 2
python scripts/cache_acm_fellow_profiles_playwright.py --data path/to/input.csv --headed --channel chrome --pause-before-read --retry-status blocked --limit-new 1
python scripts/cache_acm_fellow_profiles_playwright.py --data path/to/input.csv --cdp-url http://127.0.0.1:9222 --retry-status blocked --limit-new 2
python scripts/cache_acm_fellow_profiles_playwright.py --data path/to/input.csv --cdp-url http://127.0.0.1:9222 --retry-status blocked --delay 4 --delay-jitter 2 --batch-size 25 --batch-size-jitter 5 --batch-pause 90 --batch-pause-jitter 30
python scripts/cache_acm_fellow_profiles_playwright.py --data path/to/input.csv --cdp-url http://127.0.0.1:9222 --retry-status blocked --delay 4 --delay-jitter 2 --batch-size 25 --batch-size-jitter 5 --batch-pause 90 --batch-pause-jitter 30 --limit-batches 2
```

The script uses a persistent Chromium profile by default:

```text
.cache/playwright-acm-profile
```

Use `--headed` when ACM requires interactive browser state. If a manual challenge or cookie prompt appears, use `--pause-before-read`, complete the challenge in the opened browser window, then press Enter in the terminal so the script caches the final page HTML. Subsequent runs reuse the same local profile. `--channel chrome` uses an installed Chrome browser instead of the bundled Playwright Chromium when available. Keep the profile under `.cache/` and do not commit it.

If ACM works in a manually launched Chrome profile, connect to it over CDP:

```bash
open -na "Google Chrome" --args --remote-debugging-port=9222 --user-data-dir="$PWD/.cache/chrome-acm-cdp"
python scripts/cache_acm_fellow_profiles_playwright.py --data path/to/input.csv --cdp-url http://127.0.0.1:9222 --retry-status blocked --limit-new 2
```

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

The ACM Fellow Playwright crawler uses lighter defaults (the HTTP variant only supports the base delay, batch size, and batch pause):

- `--delay` defaults to `2.0` seconds between uncached requests.
- `--delay-jitter` defaults to `0.0`; when set, the actual sleep is randomized by plus/minus that many seconds and clamped at zero.
- `--batch-size` defaults to `50` uncached requests.
- `--batch-size-jitter` defaults to `0`; when set, each batch target is randomized by plus/minus that many requests and clamped to at least 1.
- `--batch-pause` defaults to `60.0` seconds after each batch.
- `--batch-pause-jitter` defaults to `0.0`; when set, the actual cooldown is randomized by plus/minus that many seconds and clamped at zero.
- `--limit-new N` caps uncached requests for one run.
- `--limit-batches N` caps completed batches for one run.

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
