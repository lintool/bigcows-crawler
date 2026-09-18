# Big Cows Crawler

Shared Python crawlers for ACM Fellow and Turing Award profiles, DBLP profiles, Google Scholar profiles, and CSRankings faculty data.
Applications supply their own inputs and consume cached results or explicitly requested exports.

## Setup

Clone this repository and use Python 3.10 or newer, available as `python`.
The crawlers use the standard library; no Python packages need installing.

ACM profile fetching also requires **regular Safari on macOS**.
Allow your terminal or application to control Safari when prompted, and leave the crawler's dedicated window open while it runs.
See the [Safari setup reference](README_FOR_AGENTS.md#safari-setup-and-lifecycle) for details.

## Basic Usage

Run these examples from this repository, replacing the input paths with your application's CSVs.
For a new ACM crawl, replace the example date with its start date.
Fellows and Turing Award profiles use the same runner with different award selections:

```bash
python scripts/cache_acm_fellow_profiles_safari.py --crawl-date 2026-09-14 --data /path/to/fellows.csv
python scripts/cache_acm_fellow_profiles_safari.py --award turing --crawl-date 2026-09-14 --data /path/to/turing-winners.csv
```

ACM fetching defaults to 5–7 seconds between profiles and a 60–90 second pause every 25 attempts.
Before a longer run, follow the [fresh-crawl and resume workflow](README_FOR_AGENTS.md#acm-fellow-and-turing-award-profile-crawler) to preserve the input and progress.

Other sources:

```bash
python scripts/cache_dblp_profiles.py --data /path/to/people.csv
python scripts/cache_google_scholar_profiles.py --data /path/to/people.csv
python scripts/cache_csrankings.py
```

If DBLP returns bot-check pages, use the [paced Safari workflow](README_FOR_AGENTS.md#safari-transport), which retains a resumable crawl and full page captures.

Profile inputs contain a `name` and a source-specific URL column; see the [input reference](README_FOR_AGENTS.md#inputs-and-paths) for the schema.
CSRankings downloads its faculty CSV shards without an application input.

## Results

Crawled pages and reports stay in this repository's Git-ignored `.cache/`.
ACM captures are grouped by award and crawl start date.
Scholar requests the first 100 publications per profile and retains separate raw HTML captures with a manifest for offline reprocessing.
Existing Scholar caches migrate locally on their next run; see the [capture and rebuild reference](README_FOR_AGENTS.md#raw-captures-and-offline-reprocessing).
Multiple applications can read the same captures; run writers to a shared cache sequentially.
Canonical datasets and application-specific analysis belong in the consuming application.

ACM and DBLP never edit the input CSV.
Google Scholar exports a CSV only when `--output` is supplied.
For example, export already cached Scholar results with:

```bash
python scripts/cache_google_scholar_profiles.py --data /path/to/people.csv --output /path/to/scholar-profiles.csv --limit-new 0
```

To review an existing ACM crawl without fetching or changing it, select its date:

```bash
python scripts/compare_acm_fellow_profiles.py --crawl-date 2026-09-13 --data /path/to/fellows.csv
```

This prints differences as JSON.
The matching local cache must already exist; caches are not included in a clone.
Add `--award turing` for Turing Award data.
Review differences before applying them to a dataset.

## Maintenance Reference

[README_FOR_AGENTS.md](README_FOR_AGENTS.md) contains detailed workflows, cache schemas, validation, and troubleshooting.
[AGENTS.md](AGENTS.md) defines the repository's documentation policy.
