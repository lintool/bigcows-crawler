# Big Cows Crawler

Shared Python crawlers for ACM Fellow and Turing Award profiles, DBLP profiles, Google Scholar
profiles, and CSRankings faculty data. Applications supply their own inputs and
consume cached results or explicitly requested exports.

## Setup

Use Python 3.10 or newer, available as `python`. The recommended ACM profile crawler uses **regular
Safari through AppleScript on macOS**, with only the Python standard library.
Allow the launching terminal/application to control Safari if macOS prompts.
Safari's “Allow remote automation” and “Allow JavaScript from Apple Events”
settings are not required: this crawler uses Safari's native URL/source properties.

The crawler opens its own Safari window. Leave that window open and avoid changing
its tabs while it runs; your other Safari windows remain available. It uses the
normal Safari browsing session. Playwright and Chrome are not required.

The HTTP crawlers for other sources also use only the standard library. ACM
fetching uses the Safari script; the original ACM module retains shared parsing
and cache helpers plus its legacy HTTP entry point. Use Safari for ACM fetching;
the HTTP entry point can encounter blocking.

## Commands

Run these examples from this repository. Input paths are examples; any application
can supply its own CSV. Relative input and override paths resolve from the current
working directory. Default cache/report paths resolve from the crawler repository,
even when invoked from another directory.

```bash
python scripts/cache_acm_fellow_profiles_safari.py --crawl-date 2026-09-14 --data /path/to/people.csv
python scripts/cache_acm_fellow_profiles_safari.py --award turing --crawl-date 2026-09-14 --data /path/to/turing-winners.csv
python scripts/cache_dblp_profiles.py --data /path/to/people.csv
python scripts/cache_google_scholar_profiles.py --data /path/to/people.csv
python scripts/cache_csrankings.py
```

The profile crawlers require `--data` and never choose an application's dataset
implicitly. ACM also requires `--crawl-date YYYY-MM-DD`; replace the example date
with the start date of your new crawl. CSV columns are:

| Crawler | Profile URL column | Other fields used |
| --- | --- | --- |
| ACM (Safari) | `acm_fellow_profile` | `name`; optional `year`, `location`, `citation` for comparisons |
| DBLP | `dblp_profile` | `name`; optional `acm_fellow_profile` for report context |
| Google Scholar | `google_scholar_profile` | `name`; optional `acm_fellow_profile` for report context |

For ACM comparisons, omitted optional columns are skipped. Present but blank
cells are compared, so values available for enrichment remain visible.

Blank profile URLs are skipped, duplicate URLs are fetched once, and unrelated
columns are ignored. Legacy title-cased URL columns remain supported. Scholar
also supports the legacy bundled JavaScript data format. CSRankings takes no
application input and downloads the `a`–`z` faculty CSV shards.

## Cache and exports

All default crawl artifacts live under this repository's Git-ignored `.cache/`:

```text
.cache/
  acm-fellow-profile-cache-YYYY-MM-DD.json
  acm-fellow-profile-report-YYYY-MM-DD.json
  acm-fellow-profile-state-YYYY-MM-DD.json
  acm-fellow-profile-manifest-YYYY-MM-DD.json
  acm-turing-profile-cache-YYYY-MM-DD.json
  acm-turing-profile-report-YYYY-MM-DD.json
  acm-turing-profile-state-YYYY-MM-DD.json
  acm-turing-profile-manifest-YYYY-MM-DD.json
  dblp-profile-cache.json
  dblp-profile-report.json
  google-scholar-profile-cache.json
  google-scholar-profile-report.json
  csrankings/
  csrankings-report.json
```

Profile caches are JSON objects keyed by URL, containing fetched HTML, parsed
fields, status, and timestamps. Safari reuses the existing ACM URL-keyed cache format and shared parser.
Different applications can consume the same captured profiles. ACM crawl manifests
bind each crawl to one input checksum; use the comparison command for another
application's CSV, or start a separate crawl for different fetch inputs.
Each report describes that run's input.
Default reports are replaced on subsequent runs. Use an application-specific
`--report .cache/my-app/scholar-report.json` when retaining separate reports.

Run writers to the same cache sequentially: the scripts do not lock shared caches
against simultaneous processes. Use separate cache, report, and state paths (or
`--cache-dir` for CSRankings) if independent concurrent runs are needed. Keep
overrides under `.cache/` to keep crawl artifacts out of Git.

Scholar writes no CSV by default. Export to an application only when requested:

```bash
python scripts/cache_google_scholar_profiles.py --data ../cs-big-cows/data/acm_fellows.csv --output ../cs-big-cows/data/google_scholar_profiles.csv --limit-new 0
```

Existing rows in the selected export are retained and enriched from cache;
new input profiles are appended. Use a separate output file for each application.
`--no-write-csv` is retained and suppresses an export even if `--output` is set.
The ACM and DBLP crawlers only produce caches/reports. Application-specific joins,
canonical datasets, analyses, and visualizations remain in their applications.

## Fresh ACM crawl and resuming

The shared Safari runner defaults to `--award fellows`; use `--award turing`
for Turing Award years and citations. The existing script name is retained for
compatibility. Turing mode supports both modern `awards.acm.org` profiles and
the older `amturing.acm.org` recipient layout. The URL column remains
`acm_fellow_profile` for compatibility with existing application CSVs.

Both awards can use the same `.cache/` directory and start date. Their filenames
have different prefixes, so their inputs, manifests, cache, report, and progress
remain separate. Start with an empty Turing cache for a fresh crawl; do not seed
it from the Fellows cache. With a new cache, `--prepare-only` registers the input,
writes an empty cache and a report listing missing profiles, and saves `prepared`
state without opening Safari or fetching. Existing captures are preserved:

```bash
python scripts/cache_acm_fellow_profiles_safari.py --award turing --crawl-date 2026-09-14 --data /path/to/stable-input.csv --prepare-only
```

Remove `--prepare-only` to start. Retain the same date and input snapshot to
resume. Preparation does not copy the input; save your stable snapshot under
`.cache/acm-turing-profile-input-YYYY-MM-DD.csv` before registering it. If the
actual crawl will start on a later date, prepare new paths for that date.

For read-only comparison, use `compare_acm_fellow_profiles.py --award turing`.
An explicit `--cache` can select a Fellows capture containing the same profile:
the comparison reparses raw HTML for the requested award without modifying it.
Writers cannot resume a manifest under a different award. Historical Fellows
manifests without an award field are interpreted as Fellows crawls.

Safari defaults to one profile at a time, a 5–7 second delay, and a 60–90 second
pause every 25 fetch attempts. It checks the first five fetched profiles against
the input name/year before continuing. Persistent blocking or browser errors
pause the run with a nonzero exit code; details are saved in the progress JSON.

Use a **new crawl date** for a fresh, resumable crawl that preserves earlier runs:

```bash
python scripts/cache_acm_fellow_profiles_safari.py --crawl-date 2026-09-14 --data /path/to/people.csv
```

Repeat the same command with the same input contents to resume. Successful HTML is reused, transient failures
are retried, and progress is saved after every attempt. `--limit-new 5` restricts
a trial to five profiles. `--refresh` instead refetches all selected URLs and
replaces their cache entries on success; a failed attempt preserves previously
successful HTML in that entry and records the failure as `last_attempt`.
Do not repeat `--refresh` to resume an interrupted
run. The date is the crawl's start date; keep it when resuming across midnight.
For independent runs on the same date, supply distinct `--cache`, `--report`, and
`--state` overrides under `.cache/`. Overrides change only the specified paths;
unspecified paths still use the selected date. Keep the input CSV stable during
a run, or supply a snapshot named `acm-fellow-profile-input-YYYY-MM-DD.csv`.
Capture console output as `acm-fellow-profile-log-YYYY-MM-DD.txt` if needed.
Input snapshots and log files are managed by the caller, not created automatically.
The manifest is created automatically and records the crawl date, input checksum,
and artifact paths. Reusing a crawl with changed input contents or output paths
is rejected; resuming with an identical snapshot at another path is allowed.
Keep its state file: batch counts and cooldown deadlines persist across trial
runs and resumes, with elapsed time counting toward the cooldown.

Safari saves the loaded HTML, parsed fields, timestamps, final URL, and
`fetch_method: safari-applescript`. It does **not** expose HTTP status codes or
response headers: `status_code` is `null`, and recognizable error pages are
classified from HTML. `--refresh` controls our local cache, not Safari's HTTP
cache; Safari may reuse/revalidate browser-cached responses.

There is no undated default or automatic latest-crawl selection. Select the
intended `--crawl-date` for later comparisons. An explicit `--cache` overrides the
path but does not replace the required date. Keep
application-specific crawl history and reviewed data corrections in the consuming
repository. See [the reference](README_FOR_AGENTS.md) for retry controls,
report interpretation, and troubleshooting.

## Verification

For a read-only audit against an existing crawl, use:

```bash
python scripts/compare_acm_fellow_profiles.py --crawl-date 2026-09-13 --data /path/to/people.csv
```

This reparses captured HTML, reports exact field differences, name compatibility,
blank and missing URLs, and duplicates as JSON on stdout. It can compare a changed
input without modifying any crawl files. `--output PATH` optionally writes a new
comparison file and refuses to overwrite an existing file or crawl artifact.
The name matcher accepts initials and Unicode variants but cannot establish
identity by itself; review source HTML and preserve better existing CSV values.

The crawler's `--limit-new 0` mode still writes cache, report, manifest, and progress
output for the original input without opening Safari. It uses stored parsed fields
and is not the read-only audit command.

Successful ACM entries with HTML are reused by default; transient failures and
incomplete `ok` entries are retried. `--refresh` explicitly refetches selected URLs.
For Safari, `--limit-new N` caps distinct profiles, not retry attempts. Scholar may
also refetch incomplete cache entries lacking HTML. See
[README_FOR_AGENTS.md](README_FOR_AGENTS.md) for retries, pacing, parsers, browser
sessions, and report schemas.

Run offline regression tests:

```bash
python -B -m unittest discover -s tests -v
```
