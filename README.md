# Big Cows Crawler

Shared Python crawlers for ACM Fellow profiles, DBLP profiles, Google Scholar
profiles, and CSRankings faculty data. Applications supply their own inputs and
consume cached results or explicitly requested exports.

## Setup

Use Python 3.10 or newer. The recommended ACM profile crawler uses **regular
Safari through AppleScript on macOS**, with only the Python standard library.
Allow the launching terminal/application to control Safari if macOS prompts.
Safari's “Allow remote automation” and “Allow JavaScript from Apple Events”
settings are not required: this crawler uses Safari's native URL/source properties.

The crawler opens its own Safari window. Leave that window open and avoid changing
its tabs while it runs; your other Safari windows remain available. It uses the
normal Safari browsing session. Playwright and Chrome are not required.

The HTTP crawlers for other sources also use only the standard library. ACM
fetching uses the Safari script; the original ACM module retains shared parsing
and cache helpers plus its legacy HTTP entry point. The unsuccessful ACM
Playwright transport has been removed.

## Commands

Run these examples from this repository. Input paths are examples; any application
can supply its own CSV. Relative input and override paths resolve from the current
working directory. Default cache/report paths resolve from the crawler repository,
even when invoked from another directory.

```bash
python3 scripts/cache_acm_fellow_profiles_safari.py --data /path/to/people.csv
python3 scripts/cache_dblp_profiles.py --data /path/to/people.csv
python3 scripts/cache_google_scholar_profiles.py --data /path/to/people.csv
python3 scripts/cache_csrankings.py
```

The profile crawlers require `--data` and never choose an application's dataset
implicitly. CSV columns are:

| Crawler | Profile URL column | Other fields used |
| --- | --- | --- |
| ACM (Safari) | `acm_fellow_profile` | `name`; optional `year`, `location`, `citation` for comparisons |
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
  acm-fellow-profile-cache.status.json
  dblp-profile-cache.json
  dblp-profile-report.json
  google-scholar-profile-cache.json
  google-scholar-profile-report.json
  csrankings/
  csrankings-report.json
```

Profile caches are JSON objects keyed by URL, containing fetched HTML, parsed
fields, status, and timestamps. Safari reuses the existing ACM URL-keyed cache format and shared parser.
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

## Fresh ACM crawl and resuming

Safari defaults to one profile at a time, a 5–7 second delay, and a 60–90 second
pause every 25 fetch attempts. It checks the first five fetched profiles against
the input name/year before continuing. Persistent blocking or browser errors
pause the run with a nonzero exit code; details are saved in the progress JSON.

Use a **new cache path** for a fresh, resumable crawl that preserves the old cache:

```bash
python3 scripts/cache_acm_fellow_profiles_safari.py --data /path/to/people.csv --cache .cache/acm-refresh/cache.json --report .cache/acm-refresh/report.json
```

Repeat the same command to resume. Successful HTML is reused, transient failures
are retried, and progress is saved after every attempt. `--limit-new 5` restricts
a trial to five profiles. `--refresh` instead refetches all selected URLs and
replaces their cache entries; do not repeat `--refresh` to resume an interrupted
run. Choose a new directory for each independent fresh crawl. Keep the input CSV
stable during a run, or use a local snapshot under `.cache/`.

Safari saves the loaded HTML, parsed fields, timestamps, final URL, and
`fetch_method: safari-applescript`. It does **not** expose HTTP status codes or
response headers: `status_code` is `null`, and recognizable error pages are
classified from HTML. `--refresh` controls our local cache, not Safari's HTTP
cache; Safari may reuse/revalidate browser-cached responses.

The 2026-09-13 recrawl completed with all 1,627 supplied profile URLs cached and
parsed; the reusable Safari script handled the final 1,022 fetches. Three field
differences remained for review, and the CSV was unchanged. Safari/AppleScript
sustained fetching after HTTP, Playwright, and Safari WebDriver encountered
blocking. This successful run does not guarantee future ACM availability.
See [the reference](README_FOR_AGENTS.md) for retry controls and troubleshooting.

## Verification

Cached results are reused by default. `--refresh` explicitly refetches them;
`--limit-new N` caps requests. `--limit-new 0` rebuilds cache/report output without
network requests. Safari does not open a window in this mode.
Scholar may refetch incomplete cache entries lacking HTML. See
[README_FOR_AGENTS.md](README_FOR_AGENTS.md) for retries, pacing, parsers, browser
sessions, and report schemas.

Run offline regression tests:

```bash
python3 -B -m unittest discover -s tests -v
```
