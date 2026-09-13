# Big Cows Crawler

Shared Python crawlers for ACM Fellow profiles, DBLP profiles, Google Scholar
profiles, and CSRankings faculty data. Applications supply their own inputs and
consume cached results or explicitly requested exports.

## Setup

Use Python 3.10 or newer. The HTTP crawlers use only the standard library.
For the optional ACM browser crawler:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install playwright
python -m playwright install chromium
```

## Commands

Run these examples from this repository. Input paths are examples; any application
can supply its own CSV. Relative input and override paths resolve from the current
working directory. Default cache/report paths resolve from the crawler repository,
even when invoked from another directory.

```bash
python3 scripts/cache_acm_fellow_profiles.py --data /path/to/people.csv
python3 scripts/cache_acm_fellow_profiles_playwright.py --data /path/to/people.csv --headed
python3 scripts/cache_dblp_profiles.py --data /path/to/people.csv
python3 scripts/cache_google_scholar_profiles.py --data /path/to/people.csv
python3 scripts/cache_csrankings.py
```

The profile crawlers require `--data` and never choose an application's dataset
implicitly. CSV columns are:

| Crawler | Profile URL column | Other fields used |
| --- | --- | --- |
| ACM, including Playwright | `acm_fellow_profile` | `name`; optional `year`, `location`, `citation` for comparisons |
| DBLP | `dblp_profile` | `name`; optional `acm_fellow_profile` for report context |
| Google Scholar | `google_scholar_profile` | `name`; optional `acm_fellow_profile` for report context |

Blank profile URLs are skipped, duplicate URLs are fetched once, and unrelated
columns are ignored. Legacy title-cased URL columns remain supported. Scholar
also supports the legacy bundled JavaScript data format. CSRankings takes no
application input and downloads the `a`–`z` faculty CSV shards.

## Cache and exports

All default crawl artifacts live under this repository's Git-ignored `.cache/`:

```text
.cache/
  acm-fellow-profile-cache.json
  acm-fellow-profile-report.json
  dblp-profile-cache.json
  dblp-profile-report.json
  google-scholar-profile-cache.json
  google-scholar-profile-report.json
  csrankings/
  csrankings-report.json
  playwright-acm-profile/
```

Profile caches are JSON objects keyed by URL, containing fetched HTML, parsed
fields, status, and timestamps. ACM HTTP and Playwright share a cache and parser.
Different applications reuse cached URLs; each report describes that run's input.
Default reports are replaced on subsequent runs. Use an application-specific
`--report .cache/my-app/scholar-report.json` when retaining separate reports.

Run writers to the same cache sequentially: the scripts do not lock shared caches
against simultaneous processes. Use separate `--cache` paths (or `--cache-dir`
for CSRankings) if independent concurrent runs are needed. Keep overrides under
`.cache/` to keep crawl artifacts out of Git.

Scholar writes no CSV by default. Export to an application only when requested:

```bash
python3 scripts/cache_google_scholar_profiles.py --data ../cs-big-cows/data/acm_fellows.csv --output ../cs-big-cows/data/google_scholar_profiles.csv --limit-new 0
```

Existing rows in the selected export are retained and enriched from cache;
new input profiles are appended. Use a separate output file for each application.
`--no-write-csv` is retained and suppresses an export even if `--output` is set.
The ACM and DBLP crawlers only produce caches/reports. Application-specific joins,
canonical datasets, analyses, and visualizations remain in their applications.

## Resuming and verification

Cached results are reused by default. `--refresh` explicitly refetches them;
`--limit-new N` caps requests. `--limit-new 0` rebuilds cache/report output without
network requests, though the Playwright variant still requires a browser runtime.
Scholar may refetch incomplete cache entries lacking HTML. See
[README_FOR_AGENTS.md](README_FOR_AGENTS.md) for retries, pacing, parsers, browser
sessions, and report schemas.

Run offline regression tests:

```bash
python3 -B -m unittest discover -s tests -v
```
